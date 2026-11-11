import cv2
import mss
import numpy as np
import pytesseract
import time
import pyautogui
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import Qt
import sys

# Hi-Lo Count System
running_count = 0
true_count = 0
decks_remaining = 4  # Adjust based on penetration

# Card Values for Counting
card_values = {
    "2": 1, "3": 1, "4": 1, "5": 1, "6": 1,
    "7": 0, "8": 0, "9": 0, "10": -1, "J": -1, "Q": -1, "K": -1, "A": -1
}

# Function to Capture Screen
def capture_screen(region=None):
    with mss.mss() as sct:
        screenshot = sct.grab(region if region else sct.monitors[1])
        img = np.array(screenshot)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

# Function to Detect Cards Using OCR
def detect_cards(img):
    processed_img = cv2.threshold(img, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    detected_text = pytesseract.image_to_string(processed_img, config="--psm 6")
    detected_cards = [char for char in detected_text if char in card_values.keys()]
    return detected_cards

# Function to Update Count
def update_count(detected_cards):
    global running_count, true_count
    for card in detected_cards:
        running_count += card_values[card]
    true_count = running_count / max(1, decks_remaining)

# Betting Strategy Based on True Count
def get_bet_size(tc):
    if tc <= 0:
        return 1
    elif tc == 1:
        return 2
    elif tc == 2:
        return 4
    elif tc == 3:
        return 6
    elif tc == 4:
        return 8
    else:
        return 10

# Decision Making Logic
def get_play_decision(player_hand, dealer_card, tc):
    if player_hand == "A,A" or player_hand == "8,8":
        return "Split"
    elif player_hand == "10,10":
        return "Stand"
    elif player_hand == "9,9" and dealer_card not in ["7", "10", "A"]:
        return "Split"
    elif player_hand == "11" and tc > 0:
        return "Double Down"
    elif player_hand in ["16"] and dealer_card in ["9", "10", "A"] and tc >= 0:
        return "Stand"
    return "Hit"

# GUI Overlay for macOS
class BlackjackOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Blackjack Assistant")
        self.setGeometry(50, 50, 300, 150)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)

        self.setAttribute(QtWidgets.Qt.WA_TranslucentBackground)

        self.label = QtWidgets.QLabel("Waiting for game...", self)
        self.label.setFont(QtGui.QFont("Arial", 14))
        self.label.setGeometry(20, 20, 260, 30)

        self.new_shoe_button = QtWidgets.QPushButton("New Shoe", self)
        self.new_shoe_button.setGeometry(100, 80, 100, 30)
        self.new_shoe_button.clicked.connect(self.reset_count)

    def update_display(self, bet_size, decision, count):
        self.label.setText(f"Bet: ${bet_size} | {decision} | TC: {count:.1f}")

    def reset_count(self):
        global running_count, true_count
        running_count = 0
        true_count = 0
        self.label.setText("New Shoe Started")

# Main Function
def run_bot():
    app = QtWidgets.QApplication(sys.argv)
    overlay = BlackjackOverlay()
    overlay.show()

    while True:
        img = capture_screen()
        detected_cards = detect_cards(img)
        update_count(detected_cards)

        dealer_card = "10"  # Placeholder - Add real detection here
        player_hand = "9,9"  # Placeholder - Add real detection here

        bet_size = get_bet_size(true_count)
        decision = get_play_decision(player_hand, dealer_card, true_count)

        overlay.update_display(bet_size, decision, true_count)
        time.sleep(1)

if __name__ == "__main__":
    run_bot()
