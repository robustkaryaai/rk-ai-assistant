# Pi Assistant Gemini Integration - Setup Guide

## Changes Made

Your Pi assistant now has **smart routing** for faster responses! 🚀

### What's New?

**Before:**
- All queries → Backend (slow, 3-10 seconds)

**After:**
- 💬 **Simple queries** → Gemini Direct (FAST! 1-2 seconds)
  - Conversations
  - Questions
  - Music requests
  - Alarms/timers
  - General chat
  
- 📁 **File operations** → Backend (as before)
  - Video generation
  - Image creation
  - PPT/Presentation
  - Document/DOCX
  - Text files

## Setup Instructions

### 1. Install New Dependency

On your Raspberry Pi, run:

```bash
cd /path/to/rk-ai-assistant-main
pip install -r requirements.txt
```

This will install the new `google-generativeai` package.

### 2. Add Gemini API Key

You need to add your Gemini API key to the `.env` file.

**Get your API key:**
1. Go to https://aistudio.google.com/app/apikey
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the key

**Add to `.env` file:**

Edit `rk-ai-assistant-main/rk_assistant/.env` and add:

```env
GEMINI_API_KEY=your_api_key_here
```

### 3. Optional: Configure Model

By default, the system uses `gemini-2.0-flash-exp` (fastest model). 

To change the model, add to `.env`:

```env
GEMINI_MODEL=gemini-1.5-flash
```

### 4. Optional: Disable Gemini Routing

If you want to temporarily disable Gemini and use only the backend:

```env
USE_GEMINI_DIRECT=0
```

## Testing

### Text Mode Testing

1. Start the Pi assistant:
   ```bash
   cd rk-ai-assistant-main
   python -m rk_assistant.main
   ```

2. Select **Text Mode** (option 2)

3. Test queries:

**Simple Query (Gemini):**
```
> rk what is the weather today?
```
You should see: `[text-mode] Simple query detected, routing to GEMINI`

**File Operation (Backend):**
```
> rk generate an image of a sunset
```
You should see: `[text-mode] File operation detected, routing to BACKEND`

### Voice Mode Testing

After text mode testing works:

1. Start the Pi assistant
2. Select **Voice Mode** (option 1)
3. Say: "RK, what time is it?" (should use Gemini - fast!)
4. Say: "RK, create a video of a cat" (should use Backend)

## Troubleshooting

### "Gemini not configured, routing to BACKEND"

This means the `GEMINI_API_KEY` is not set in your `.env` file. The system will fall back to using the backend (slower but still works).

### "Gemini error: ..."

If Gemini fails, the system automatically falls back to the backend. Check:
- API key is valid
- You have internet connection
- API quota is not exceeded

### "ModuleNotFoundError: google.generativeai"

Run: `pip install google-generativeai`

## Performance Expectations

**Simple queries (Gemini path):**
- Response time: 1-2 seconds ✨
- No backend load
- Works even if backend is sleeping

**File operations (Backend path):**
- Response time: Same as before (3-10 seconds)
- Backend processes complex requests
- Creates actual files/media

## Files Changed

- ✅ `requirements.txt` - Added `google-generativeai`
- ✅ `rk_assistant/gemini_client.py` - New Gemini client module
- ✅ `rk_assistant/config.py` - Added Gemini configuration
- ✅ `rk_assistant/intent_classifier.py` - Added `needs_backend()` function
- ✅ `rk_assistant/main.py` - Implemented smart routing logic

## Architecture

```
User Query
    │
    ├─ Wake word detected
    │
    ├─ Intent Classification
    │   │
    │   ├─ File operation? → Backend
    │   │   (video, image, ppt, docx)
    │   │
    │   └─ Simple query? → Gemini Direct ⚡
    │       (chat, questions, music, alarms)
    │
    └─ Speak Response
```

Enjoy your faster Pi assistant! 🎉
