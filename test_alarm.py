#!/usr/bin/env python3
"""Test alarm sound playback."""

import pygame
import time
from pathlib import Path

print("Testing alarm sound playback...")

# Initialize pygame mixer
try:
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
    pygame.mixer.set_num_channels(4)
    print("✓ Pygame mixer initialized")
except Exception as e:
    print(f"❌ Error initializing mixer: {e}")
    exit(1)

# Load alarm sound
alarm_file = Path("alarm.wav")
if not alarm_file.exists():
    print(f"❌ Alarm file not found: {alarm_file}")
    exit(1)

try:
    alarm_sound = pygame.mixer.Sound(str(alarm_file))
    alarm_sound.set_volume(1.0)
    print(f"✓ Loaded alarm sound: {alarm_file}")
    print(f"  Duration: {alarm_sound.get_length():.2f} seconds")
except Exception as e:
    print(f"❌ Error loading sound: {e}")
    exit(1)

# Test playback
try:
    print("\n▶️ Playing alarm in 2 seconds...")
    time.sleep(2)
    
    channel = pygame.mixer.find_channel()
    if channel:
        channel.play(alarm_sound)
        print("✓ Alarm playing! (Playing for 5 seconds...)")
        time.sleep(5)
        print("✓ Test complete!")
    else:
        print("❌ No available mixer channels")
except Exception as e:
    print(f"❌ Error playing alarm: {e}")
    exit(1)
