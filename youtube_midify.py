import sys
import getopt
import cv2
import numpy as np
import yt_dlp
import os
from mido import Message, MidiFile, MidiTrack

# Global settings
__activationThreshold = 30
__whiteThreshold = 150
__minKeyWidth = 3
__blackThreshold = 100
__keyboardHeight = 0.85
__start = 6
__end = -1
__output = "out.mid"
__keyPositions = []
__defaultValues = []
__middleC = 0

def __labelKeys(keyboard):
    cs = []
    global __middleC
    for i in range(len(__defaultValues)-6):
        if(__defaultValues[i]>__whiteThreshold and 
           __defaultValues[i+1]>__whiteThreshold and 
           __defaultValues[i+2]<__blackThreshold and 
           __defaultValues[i+3]>__whiteThreshold and 
           __defaultValues[i+4]<__blackThreshold and 
           __defaultValues[i+5]>__whiteThreshold and 
           __defaultValues[i+6]>__whiteThreshold):
            cs.append(i+1)

    if len(cs) == 0:
        print("Did not detect a valid keyboard at the specified start. Check start time/keyboard height.")
        sys.exit(2)
    __middleC = cs[int((len(cs))/2)]
    print(f"Recognized key {__middleC} as middle C.")

def __getPressedKeys(keys):
    return [1 if abs(keys[i] - __defaultValues[i]) > __activationThreshold else 0 for i in range(len(keys))]

def __extractKeyPositions(keyboard):
    global __keyPositions, __defaultValues, __whiteThreshold, __blackThreshold
    inWhiteKey = inBlackKey = False
    keyStart = 0
    maxB, minB = max(keyboard), min(keyboard)
    __whiteThreshold = minB + (maxB - minB) * 0.6
    __blackThreshold = minB + (maxB - minB) * 0.4

    for i, b in enumerate(keyboard):
        if b > __whiteThreshold:
            if not inWhiteKey and not inBlackKey:
                inWhiteKey, keyStart = True, i
        else:
            if inWhiteKey:
                inWhiteKey = False
                if i - keyStart > __minKeyWidth:
                    pos = int((keyStart + i) / 2)
                    __keyPositions.append(pos)
                    __defaultValues.append(keyboard[pos])

        if b < __blackThreshold:
            if not inBlackKey and not inWhiteKey:
                inBlackKey, keyStart = True, i
        else:
            if inBlackKey:
                inBlackKey = False
                if i - keyStart > __minKeyWidth:
                    pos = int((keyStart + i) / 2)
                    __keyPositions.append(pos)
                    __defaultValues.append(keyboard[pos])
    print(f"Detected {len(__keyPositions)} keys.")

from mido import Message, MidiFile, MidiTrack, MetaMessage, bpm2tempo

def convert(video, is_url, output="out.mid", start=0, end=-1, keyboard_height=0.85, threshold=30):
    global __activationThreshold
    __activationThreshold = threshold
    
    mid = MidiFile()
    track = MidiTrack()
    mid.tracks.append(track)

    # 1. SET THE TEMPO (120 BPM is standard for MIDI)
    mid.ticks_per_beat = 480
    bpm = 120
    track.append(MetaMessage('set_tempo', tempo=bpm2tempo(bpm)))
    
    # Calculate how many MIDI ticks occur per second
    # Formula: (ticks/beat) * (beats/minute) / (seconds/minute)
    ticks_per_second = mid.ticks_per_beat * (bpm / 60)

    if is_url:
        print("Downloading video...")
        if not os.path.exists('videos'): os.makedirs('videos')
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': 'videos/%(id)s.%(ext)s',
            'quiet': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video, download=True)
            inputVideo = ydl.prepare_filename(info)
    else:
        inputVideo = video
    
    vidcap = cv2.VideoCapture(inputVideo)
    success, image = vidcap.read()
    if not success: sys.exit(f"Could not open video: {inputVideo}")

    count = 0
    lastMod = 0
    fps = vidcap.get(cv2.CAP_PROP_FPS)
    h, w, _ = image.shape
    kb_pixel_h = int(h * keyboard_height)
    startF, endF = int(start * fps), int(end * fps)
    lastPressed = []

    while success:
        ia = np.asarray(image)
        kb = [np.mean(ia[kb_pixel_h][x]) for x in range(w)]

        if count == startF:
            __extractKeyPositions(kb)
            __labelKeys(kb)
            lastPressed = [0] * len(__keyPositions)
            debug_img = image.copy()
            cv2.line(debug_img, (0, kb_pixel_h), (w, kb_pixel_h), (0, 255, 0), 2)
            cv2.imwrite("debug_alignment.jpg", debug_img)

        if count >= startF:
            pressed = __getPressedKeys([kb[p] for p in __keyPositions])
            for i in range(len(pressed)):
                if not pressed[i] == lastPressed[i]:
                    # 2. THE FIX: Convert frame-delta into tick-delta
                    # frames_elapsed = (count - lastMod)
                    # seconds_elapsed = frames_elapsed / fps
                    # delta_ticks = seconds_elapsed * ticks_per_second
                    delta = int(((count - lastMod) / fps) * ticks_per_second)
                    
                    note = 60 - __middleC + i
                    msg = 'note_on' if pressed[i] == 1 else 'note_off'
                    
                    # Note: Use velocity 0 for note_off or velocity 64 for note_on
                    velocity = 64 if pressed[i] == 1 else 0
                    
                    track.append(Message(msg, note=note, velocity=velocity, time=delta))
                    lastMod = count
            
            if count % 30 == 0: print(f"Processing frame {count}...", end="\r")
            lastPressed = pressed

        success, image = vidcap.read()
        count += 1
        if 0 < endF < count: break

    mid.save(output)
    print(f"\nSaved as {output}!")
def __parse_options(argv):
    global __video, __is_url, __output, __start, __end, __keyboardHeight, __activationThreshold
    if not argv: 
        print("Usage: python youtube_midify.py <url> -o <out.mid>"); sys.exit()
    __video, __is_url = argv[0], not argv[0].endswith(".mp4")
    opts, _ = getopt.getopt(argv[1:],"ho:s:e:k:t:",["output=","start=","end=","keyboard_height=","threshold="])
    for opt, arg in opts:
        if opt in ("-o", "--output"): __output = arg
        elif opt in ("-s", "--start"): __start = float(arg)
        elif opt in ("-e", "--end"): __end = float(arg)
        elif opt in ("-k", "--keyboard_height"): __keyboardHeight = float(arg)
        elif opt in ("-t", "--threshold"): __activationThreshold = int(arg)

if __name__ == "__main__":
    __parse_options(sys.argv[1:])
    convert(__video, __is_url, __output, __start, __end, __keyboardHeight, __activationThreshold)