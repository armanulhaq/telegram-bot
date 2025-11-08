import os
import re
from dotenv import load_dotenv
import google.generativeai as genai
from googleapiclient.discovery import build
from telegram.ext import Updater, MessageHandler, Filters, CommandHandler
from telegram import ParseMode
import random

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# Configure Gemini AI
genai.configure(api_key=GEMINI_API_KEY)

# Configure YouTube API
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY, static_discovery=False)

# Create Gemini model
model = genai.GenerativeModel("gemini-2.5-flash")


def extract_video_id(url):
    """
    This function takes a YouTube URL and extracts just the video ID
    Example: "https://youtube.com/watch?v=ABC123" → "ABC123"
    """
    patterns = [
        r'(?:v=|/)([0-9A-Za-z_-]{11}).*',  # Matches youtube.com/watch?v=...
        r'(?:embed/)([0-9A-Za-z_-]{11})',   # Matches youtube.com/embed/...
        r'youtu\.be/([0-9A-Za-z_-]{11})'    # Matches youtu.be/...
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)  # Return the video ID
    return None  # Return None if no match found


def format_duration(duration):
    """
    Converts YouTube's time format (PT1H23M45S) to readable format (1h 23m 45s)
    """
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return "Unknown"

    hours, minutes, seconds = match.groups()
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")

    return " ".join(parts) if parts else "0s"


def format_views(count):
    """
    Formats large numbers to readable format
    Example: 1500000 → "1.5M", 5000 → "5.0K"
    """
    count = int(count)
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def get_detective_reaction(bias_level, factuality):
    """
    Generates Jaime's short detective comment based on the video's trustworthiness
    Returns a fun but professional assessment
    """
    reactions = {
        "low_factual": [
            "😽 *Jaime's Take:* This one smells fresh! Content appears credible and well-researched.",
            "😽😽 *Jaime's Take:* My whiskers approve! Solid information with minimal bias detected.",
            "😽😽😽 *Jaime's Take:* Investigation complete - this checks out as trustworthy content."
        ],
        "moderate_mixed": [
            "🙀 *Jaime's Take:* Something fishy here... Mixed signals detected. Cross-reference recommended.",
            "🙀🙀 *Jaime's Take:* Partial truth alert! Contains both facts and opinions - view critically.",
            "🙀🙀🙀 *Jaime's Take:* My detective senses tingling. Not entirely objective - proceed with awareness."
        ],
        "high_questionable": [
            "😾😾😾 *Jaime's Take:* RED FLAG! High bias detected. This content may be misleading or agenda-driven.",
            "😾 *Jaime's Take:* Strong commercial/ideological bias present. Verify claims independently.",
            "😾😾 *Jaime's Take:* Suspicious content detected. Treat claims with significant skepticism."
        ]
    }

    # Determine which category based on bias and factuality levels
    bias_lower = bias_level.lower()
    fact_lower = factuality.lower()

    if "low" in bias_lower and "factual" in fact_lower:
        category = "low_factual"
    elif "high" in bias_lower or "questionable" in fact_lower:
        category = "high_questionable"
    else:
        category = "moderate_mixed"

    return random.choice(reactions[category])


def summarize_youtube(update, context, url):
    """
    Main function that analyzes a YouTube video
    1. Extracts video ID
    2. Fetches video details from YouTube
    3. Sends to Gemini AI for analysis
    4. Formats and sends the response
    """
    msg = update.effective_message

    # Show a random fun loading message
    loading_messages = [
        "🔍 Investigating the evidence...",
        "🕵️ Detective Jaime on the case...",
        "👃 Analyzing content patterns...",
        "📋 Gathering intelligence..."
    ]
    status_msg = msg.reply_text(random.choice(loading_messages))

    # Extract the video ID from the URL
    video_id = extract_video_id(url)
    if not video_id:
        status_msg.edit_text("❌ *Invalid Evidence:* That's not a valid YouTube link. Please provide a proper URL.")
        return

    try:
        # Fetch video information from YouTube API
        info = youtube.videos().list(
            part="snippet,contentDetails,statistics",  # What info to fetch
            id=video_id  # Which video
        ).execute()

        # Check if video exists
        if not info.get("items"):
            status_msg.edit_text("❌ *Video Not Found:* This video is unavailable or has been removed.")
            return

        # Extract all the video details
        video_data = info["items"][0]
        snippet = video_data["snippet"]
        stats = video_data.get("statistics", {})
        content_details = video_data.get("contentDetails", {})

        title = snippet["title"]
        description = snippet.get("description", "No description available")
        channel = snippet.get("channelTitle", "Unknown")
        duration = format_duration(content_details.get("duration", "PT0S"))
        views = format_views(stats.get("viewCount", 0))

    except Exception as e:
        status_msg.edit_text(f"❌ *Fetch Error:* Unable to retrieve video data: {str(e)}")
        return

    # Update status message
    status_msg.edit_text("🤖 Running analysis algorithms...")

    # Create the prompt for Gemini AI
    prompt = f"""
Analyze this YouTube video and provide a professional assessment:

Title: {title}
Channel: {channel}
Description: {description}

**FORMAT YOUR RESPONSE EXACTLY LIKE THIS:**

Key Points:
- [First main point - be specific and clear]
- [Second main point]
- [Third main point]
- [Fourth main point]
- [Fifth main point]

Quick Analysis:
Bias: [Low/Moderate/High]
[Brief professional explanation]

Factuality: [Factual/Opinion/Mixed]
[Brief professional assessment]

Type: [News/Educational/Entertainment/Commentary]

Keep it concise and professional. Each bullet should be 1-2 sentences max.
"""

    try:
        # Send to Gemini AI for analysis
        result = model.generate_content([prompt])
        analysis = result.text.strip()

        # Extract bias and factuality levels to generate Jaime's reaction
        bias_match = re.search(r'Bias:\s*(\w+)', analysis)
        fact_match = re.search(r'Factuality:\s*(\w+)', analysis)

        bias_level = bias_match.group(1) if bias_match else "Unknown"
        factuality = fact_match.group(1) if fact_match else "Unknown"

        # Get Jaime's detective reaction
        detective_reaction = get_detective_reaction(bias_level, factuality)

        # Build the final response message
        response = f"🕵️ *INVESTIGATION REPORT #{random.randint(1000, 9999)}*\n"
        response += f"━━━━━━━━━━━━━━━━━━\n\n"
        response += f"*Title:* {title}\n"
        response += f"*Channel:* {channel}\n"
        response += f"*Duration:* {duration}\n"
        response += f"*Views:* {views}\n"
        response += f"*Link:* https://youtube.com/watch?v={video_id}\n\n"
        response += f"{analysis}\n\n"  # AI analysis
        response += f"━━━━━━━━━━━━━━━━━━\n"
        response += f"{detective_reaction}"  # Jaime's verdict

        # Send the formatted response
        status_msg.edit_text(response, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except Exception as e:
        status_msg.edit_text(f"❌ *Analysis Error:* {str(e)}")


def start_command(update, context):
    """
    Handles /start command - shows welcome message
    """
    welcome = """
🕵️ *Detective Jaime - YouTube Investigator*

Professional video content analysis with a feline touch.

*Services Offered:*
✓ Comprehensive video summaries
✓ Bias detection & assessment
✓ Fact-checking analysis
✓ Content credibility evaluation

*How It Works:*
Simply send any YouTube link and receive a detailed investigation report.

*Example:*
`https://youtube.com/watch?v=...`

Ready to investigate? Send me a link! 🐟
"""
    update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)


def help_command(update, context):
    """
    Handles /help command - shows usage guide
    """
    help_text = """
🔍 *Investigation Services*

*What I Analyze:*
- 5-point content summaries
- Bias levels (Low/Moderate/High)
- Factuality assessment (Factual/Opinion/Mixed)
- Content type classification
- Overall credibility verdict

*How to Use:*
1️⃣ Send me any YouTube link
2️⃣ Wait for the investigation (5-10 seconds)
3️⃣ Receive comprehensive analysis

*Available Commands:*
/start - Introduction
/help - This guide
/about - About Detective Jaime

*Note:* Analysis based on video title, description, and metadata. For best results, works with videos that have detailed descriptions.
"""
    update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


def about_command(update, context):
    """
    Handles /about command - tells Jaime's backstory
    """
    about_text = """
🐱 *About Detective Jaime*

*Background:*
Graduate of the Feline Investigation Academy, specializing in digital content analysis and pattern recognition.

*Expertise:*
YouTube content investigation, bias detection, misinformation identification, and credibility assessment.

*Mission:*
To help users make informed decisions about online video content through professional, unbiased analysis.

*Methods:*
Combines AI-powered content analysis with pattern recognition to detect bias, assess factuality, and evaluate source credibility.

*Status:* Active duty, 24/7 investigations available

🐟 *Powered by:* Gemini AI + YouTube Data API
"""
    update.message.reply_text(about_text, parse_mode=ParseMode.MARKDOWN)


def handle_message(update, context):
    """
    Handles all text messages
    Checks if it's a YouTube link, then processes it
    """
    text = update.effective_message.text
    if text and ("youtube.com" in text or "youtu.be" in text):
        # It's a YouTube link - analyze it
        summarize_youtube(update, context, text)
    else:
        # Not a YouTube link - send helpful message
        reactions = [
            "🤔 That's not a YouTube link. Please send a valid YouTube URL for analysis.",
            "❓ I need a YouTube link to investigate. Try: youtube.com/watch?v=...",
            "🐟 Send me a YouTube link and I'll analyze it for you!"
        ]
        update.message.reply_text(random.choice(reactions))


def main():
    """
    Main function - starts the bot and sets up handlers
    """
    # Create the bot updater
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Add command handlers (for /start, /help, /about)
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("about", about_command))

    # Add message handler (for YouTube links)
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    # Print startup message
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🕵️ Detective Jaime is active!")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🐟 Status: Ready for investigations")
    print("📋 Awaiting YouTube links...")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Start the bot
    updater.start_polling()  # Continuously checks for new messages
    updater.idle()  # Keeps the bot running


# Run the bot when script is executed
if __name__ == "__main__":
    main()
