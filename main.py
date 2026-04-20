import speech_recognition as sr

import webbrowser
import pyttsx3
import melodylibrary
import requests

from google import genai
from google.genai import types
from gtts import gTTS
import pygame
import time
import os

recognizer = sr.Recognizer()
engine = pyttsx3.init()
newsapi = "4f292a07c3ee4ad3bfa6bcfb52b2051e"
def speak_old(text):
    # Legacy TTS using pyttsx3 (offline, kept as fallback)
    engine.say(text)
    engine.runAndWait()

def speak(text):
    # Convert text to speech using Google TTS and save as temp MP3
    tts = gTTS(text)
    tts.save('temp.mp3')
    # Initialize pygame audio engine and load the generated file
    pygame.init()
    pygame.mixer.init()
    pygame.mixer.music.load("temp.mp3")
    pygame.mixer.music.play()

    print("Playing music...")

    # Block execution until the audio finishes playing
    while pygame.mixer.music.get_busy():
        time.sleep(1)
    # Release the file handle before deleting
    pygame.mixer.music.unload()
    os.remove("temp.mp3")
    print("Finished!")


def aiProcess(command):
    # Initialize the Gemini client with API key
    client = genai.Client(
        api_key="AIzaSyCMaazkyLh1E4RPaoTTH8IN5DmAJVr4u10"
    )

    # Send the user's command to Gemini with a system persona defined
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction="You are a virtual assistant named jarvis skilled in general tasks like Alexa and Google. Give short responeses."
        ),
        contents=command
    )
    return response.text

def processCommand(c):
    # Route the command to the appropriate handler based on keywords
    if "open google" in c.lower():
        webbrowser.open("https://www.google.com")
    elif "open facebook" in c.lower():
        webbrowser.open("https://www.facebook.com")
    elif "open linkedin" in c.lower():
        webbrowser.open("https://www.linkedin.com")
    elif "open youtube" in c.lower():
        webbrowser.open("https://www.youtube.com")
    elif c.lower().startswith("play"):
        # Extract song name from command and look up its URL in the local melody library
        song = c.lower().split(" ")[1]
        link = melodylibrary.melody[song]
        webbrowser.open(link)

    elif "headlines" in c.lower():
        # Fetch top US headlines from NewsAPI
        r = requests.get(f"https://newsapi.org/v2/top-headlines?country=us&apiKey={newsapi}")

        if r.status_code == 200:
            data = r.json()
            articles = data.get('articles', [])

            # Read out each headline one by one
            for article in articles:
                speak(article['title'])

                # After each headline, briefly listen for a "stop" command
                # If nothing is said or recognition fails, continue to next headline
                try:
                    stop = sr.Recognizer()
                    with sr.Microphone() as source:
                        stop_audio = stop.listen(source, timeout=2, phrase_time_limit=2)
                        stop_command = stop.recognize_google(stop_audio)
                        if "stop" in stop_command.lower():
                            speak("Stopping news.")
                            break
                except:
                    pass

    else:
        # Command didn't match any built-in — delegate to Gemini AI
        output = aiProcess(c)
        speak(output)

if __name__ == "__main__":
    speak("Initializing Jarvis....")
    # Main loop — constantly listens for the wake word "Jarvis"
    while True:
        r = sr.Recognizer()     #Processes the command
        print("Recognizing") 
        try:
            # Phase 1: Listen for wake word with a short phrase limit
            with sr.Microphone() as source:
                print("Listening....")
                audio = r.listen(source, timeout=5, phrase_time_limit=3)


            word = r.recognize_google(audio)    #To transcribe the audio

            if "jarvis" in word.lower():
                speak("Yaa")

                # Phase 2: Wake word detected, now listen for the actual command
                # Longer phrase_time_limit allows more complex commands
                with sr.Microphone() as source:
                    print("Jarvis Active....")
                    audio = r.listen(source, timeout=5, phrase_time_limit=10)
                    command = r.recognize_google(audio)
                processCommand(command)

        except Exception as e:
            # Catches timeout errors, unrecognized speech, mic issues, etc.
            print("Error; {0}".format(e))