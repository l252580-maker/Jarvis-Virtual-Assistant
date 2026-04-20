# Jarvis - AI-Powered Voice Assistant

A Python-based desktop voice assistant with a futuristic PyQt5 GUI. Jarvis listens for a wake word, processes natural language commands, responds via text-to-speech, and handles tasks including web browsing, music playback, and live news headlines. Unrecognized commands are routed to the Google Gemini API for AI-generated responses.

---

## Features

- Wake word detection ("Jarvis") with a continuous auto-listen loop
- Natural language command processing
- AI responses powered by Google Gemini 2.5 Flash
- Text-to-speech output via Google Text-to-Speech (gTTS) and pygame
- Web navigation for Google, YouTube, Facebook, and LinkedIn
- Music playback via a configurable song library
- Live top headlines fetched from NewsAPI
- Futuristic dark-theme PyQt5 desktop interface with animated microphone and chat log
- Manual mic button and text input as alternatives to voice

---

## Project Structure

```
jarvis-assistant/
├── main.py              # Backend: speech recognition, command processing, AI, TTS
├── melodylibrary.py     # Song name to URL mapping dictionary
├── jarvis_gui.py        # PyQt5 desktop GUI wrapping the backend
└── requirements.txt     # Python dependencies
```

---

## Requirements

- Python 3.10 or higher
- A working microphone
- Internet connection (for Gemini API, gTTS, and NewsAPI)

---

## API Configuration

Before running the application, you must configure three API keys inside `main.py`.

### 1. Google Gemini API Key

Used for AI-generated responses to unrecognized commands.

1. Go to https://aistudio.google.com/app/apikey
2. Create a new API key
3. Open `main.py` and replace the value in `aiProcess()`:

```python
client = genai.Client(
    api_key="YOUR_GEMINI_API_KEY_HERE"
)
```

### 2. NewsAPI Key

Used to fetch top US headlines.

1. Register for a free account at https://newsapi.org/register
2. Copy your API key from the dashboard
3. Open `main.py` and replace the value at the top of the file:

```python
newsapi = "YOUR_NEWSAPI_KEY_HERE"
```

### 3. gTTS

Google Text-to-Speech uses a public endpoint and does not require an API key, but does require an active internet connection.

---

## Installation

### Step 1: Clone the repository

```bash
git clone https://github.com/your-username/jarvis-assistant.git
cd jarvis-assistant
```

### Step 2: Install PyAudio (microphone dependency)

PyAudio requires PortAudio to be installed at the system level before the Python package can be built.

**Windows**
```bash
pip install pyaudio
```

**macOS**
```bash
brew install portaudio
pip install pyaudio
```

**Linux (Ubuntu/Debian)**
```bash
sudo apt install portaudio19-dev
pip install pyaudio
```

### Step 3: Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure API keys

Edit `main.py` and insert your Gemini API key and NewsAPI key as described in the API Configuration section above.

---

## Running the Application

```bash
python jarvis_gui.py
```

---

## Usage

### Auto-Listen Mode

Click the "Auto-Listen: OFF" toggle in the top-right corner to enable continuous listening. The assistant will:

1. Listen for the wake word "Jarvis"
2. Acknowledge and listen for your command
3. Process and respond
4. Automatically return to step 1

This loop continues until you toggle Auto-Listen off.

### Manual Mic Button

Click the microphone button in the centre of the window to capture a single command without using the wake word.

### Text Input

Type any command or question in the input bar at the bottom and press Enter or click Send.

### Quick Action Buttons

Click any button in the sidebar Quick Actions panel to trigger a command instantly.

### Supported Voice Commands

| Command | Action |
|---|---|
| "Open Google" | Opens google.com in the browser |
| "Open YouTube" | Opens youtube.com in the browser |
| "Open Facebook" | Opens facebook.com in the browser |
| "Open LinkedIn" | Opens linkedin.com in the browser |
| "Play [song name]" | Plays a song from melodylibrary.py |
| "Headlines" | Reads and displays top US news headlines |
| Anything else | Sent to Gemini AI for a response |

---

## Adding Songs

Open `melodylibrary.py` and add entries using the song name as the key and the YouTube URL as the value:

```python
melody = {
    "unstoppable": "https://youtu.be/oS07d8Gr4tw",
    "your song":   "https://youtu.be/your_video_id",
}
```

The song name must be a single lowercase word. Say "Play unstoppable" to play it.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Window closes immediately | Check the terminal for error output. Ensure all dependencies are installed. |
| Microphone not detected | Install PyAudio and verify microphone permissions in your OS settings |
| Gemini API error | Verify your API key is correct and the google-genai package is installed |
| NewsAPI returns no articles | Verify your NewsAPI key and check free-tier quota |
| No audio output | Check internet connection (gTTS requires network access) |

---

## Technologies Used

- Python 3.10+
- PyQt5 - Desktop GUI
- SpeechRecognition - Microphone input and speech-to-text
- Google Gemini API - AI-generated responses
- gTTS - Text-to-speech output
- pygame - Audio playback
- NewsAPI - Live news headlines
- requests - HTTP client

---
