import cv2
import numpy as np
import pygame
import logging
from pathlib import Path
from datetime import datetime
import csv
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("drowsiness_detection.log")]
)
logger = logging.getLogger(__name__)

# Create drowsiness_data directories
DATA_DIR = Path("drowsiness_data")
IMAGES_DIR = DATA_DIR / "images"
DATA_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

# ==================== CONSTANTS ====================
FPS = 30
TRIGGER_FRAMES = 120  # Exactly 4 seconds at 30 FPS
CLOSED_THRESHOLD = 0.40  # Optimized threshold for eyes closed detection


class DrowsinessDetector:
    def __init__(self, alarm_file="alarm.wav"):
        """Initialize drowsiness detector."""
        self.alarm_file = Path(alarm_file)
        
        # Setup CSV file for logging drowsiness events
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_file = DATA_DIR / f"drowsiness_log_{timestamp}.csv"
        self.csv_writer = None
        self.init_csv_file()
        
        # Audio setup
        try:
            pygame.mixer.init()
            if self.alarm_file.exists():
                self.alarm_sound = pygame.mixer.Sound(str(self.alarm_file))
                logger.info("[OK] Alarm loaded")
            else:
                logger.error(f"Alarm file not found: {self.alarm_file}")
                self.alarm_sound = None
        except Exception as e:
            logger.error(f"Audio error: {e}")
            self.alarm_sound = None
        
        # Load cascades
        cascade_path = cv2.data.haarcascades
        self.face_cascade = cv2.CascadeClassifier(
            cascade_path + 'haarcascade_frontalface_default.xml'
        )
        self.eye_cascade = cv2.CascadeClassifier(
            cascade_path + 'haarcascade_eye.xml'
        )
        logger.info("[OK] Face & eye cascades loaded")
        
        # Camera setup
        try:
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                raise Exception("Camera not available")
            
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, FPS)
            logger.info("[OK] Camera ready")
        except Exception as e:
            logger.error(f"Camera error: {e}")
            raise
        
        # State variables - CRITICAL: proper initialization
        self.closed_frames = 0
        self.open_frames = 0
        self.alarm_on = False
        self.last_ear = 0.5
        
        # Use pygame for display instead of cv2.imshow
        self.use_pygame_display = True
        try:
            pygame.init()
            self.screen = pygame.display.set_mode((640, 480))
            pygame.display.set_caption("Drowsiness Detection v3.0 (PRODUCTION)")
            logger.info("[OK] Pygame display initialized")
        except Exception as e:
            logger.warning(f"Pygame display init failed: {e}")
            self.use_pygame_display = False
        
        logger.info("[OK] System ready - Close eyes for 4 seconds")
    
    def init_csv_file(self):
        """Initialize CSV file for logging drowsiness events."""
        try:
            with open(self.csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Timestamp', 'Event', 'Duration (seconds)', 'Closure Score', 'Image Path'])
            logger.info(f"[OK] CSV file created: {self.csv_file}")
        except Exception as e:
            logger.error(f"Error creating CSV file: {e}")
    
    def log_event(self, event, duration, score, image_path=None):
        """Log drowsiness event to CSV file."""
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([timestamp, event, f"{duration:.2f}", f"{score:.4f}", image_path or ""])
        except Exception as e:
            logger.error(f"Error logging event: {e}")
    
    def save_frame(self, frame, event_type):
        """Save frame to drowsiness_data/images folder."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"drowsiness_{event_type}_{timestamp}.jpg"
            filepath = IMAGES_DIR / filename
            cv2.imwrite(str(filepath), frame)
            logger.info(f"[SAVED] Image: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error saving frame: {e}")
            return None
    
    def calculate_eye_closure_score(self, eye_region):
        """
        Calculate comprehensive eye closure score (0.0 = open, 1.0 = closed).
        Uses multiple methods for accuracy.
        """
        if eye_region.size == 0:
            return 0.5
        
        try:
            h, w = eye_region.shape[:2]
            if h < 10 or w < 10:
                return 0.5
            
            # Histogram equalization
            gray_eq = cv2.equalizeHist(eye_region)
            
            # 1. Darkness ratio (closed eyes are darker)
            dark_pixels = np.sum(gray_eq < 70)
            darkness_ratio = dark_pixels / eye_region.size
            
            # 2. Edge detection (open eyes have sharp features)
            edges = cv2.Canny(gray_eq, 30, 100)
            edge_ratio = np.sum(edges > 0) / eye_region.size
            
            # 3. Contour analysis
            _, binary = cv2.threshold(gray_eq, 50, 255, cv2.THRESH_BINARY_INV)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            
            max_area = 0
            if contours:
                max_area = max(cv2.contourArea(c) for c in contours)
            contour_ratio = max_area / (h * w) if h * w > 0 else 0
            
            # 4. Brightness (eye white visible when open)
            brightness = np.mean(gray_eq) / 255.0
            
            # 5. Variance/Sharpness
            laplacian_var = cv2.Laplacian(gray_eq, cv2.CV_64F).var()
            sharpness = min(1.0, laplacian_var / 200.0)
            
            # Weighted combination
            # Closed eyes: high darkness, low edges, low contours, low brightness, low sharpness
            closeness_score = (
                (darkness_ratio * 0.35) +
                ((1.0 - edge_ratio) * 0.25) +
                ((1.0 - contour_ratio) * 0.20) +
                ((1.0 - brightness) * 0.15) +
                ((1.0 - sharpness) * 0.05)
            )
            
            return np.clip(closeness_score, 0.0, 1.0)
        
        except Exception as e:
            logger.error(f"Eye closure calculation error: {e}")
            return 0.5
    
    def detect_eyes_closed(self, frame_gray):
        """Detect if eyes are closed using cascade + closure score."""
        try:
            # Face detection
            faces = self.face_cascade.detectMultiScale(frame_gray, 1.3, 5)
            
            if len(faces) == 0:
                return False, 0.5
            
            face = faces[0]
            fx, fy, fw, fh = face
            face_roi = frame_gray[fy:fy+fh, fx:fx+fw]
            
            # Eye detection
            eyes = self.eye_cascade.detectMultiScale(face_roi, 1.05, 5)
            
            if len(eyes) < 2:
                return False, 0.5
            
            eyes = sorted(eyes, key=lambda e: e[0])[:2]
            
            # Calculate closure score for each eye
            scores = []
            for (ex, ey, ew, eh) in eyes:
                if ew > 10 and eh > 10:
                    eye_region = face_roi[ey:ey+eh, ex:ex+ew]
                    score = self.calculate_eye_closure_score(eye_region)
                    scores.append(score)
            
            if not scores:
                return False, 0.5
            
            avg_score = np.mean(scores)
            
            # Threshold: score > 0.40 = eyes closed
            is_closed = avg_score > CLOSED_THRESHOLD
            
            return is_closed, avg_score
        
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return False, 0.5
    
    def play_alarm(self):
        """Play alarm sound."""
        try:
            if self.alarm_sound:
                channel = pygame.mixer.find_channel()
                if channel:
                    channel.play(self.alarm_sound)
        except Exception as e:
            logger.error(f"Play error: {e}")
    
    def stop_alarm(self):
        """Stop alarm sound - CRITICAL for proper operation."""
        try:
            pygame.mixer.stop()
        except:
            pass
    
    def run(self):
        """Main detection loop - CRITICAL: proper state machine."""
        logger.info("Starting... Press Q to quit")
        
        try:
            running = True
            while running:
                ret, frame = self.cap.read()
                if not ret:
                    break
                
                frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # Detect eye state
                eyes_closed, closure_score = self.detect_eyes_closed(gray)
                self.last_ear = closure_score
                
                # ===== CRITICAL STATE MACHINE =====
                
                if eyes_closed:
                    # EYES ARE CLOSED
                    self.closed_frames += 1
                    self.open_frames = 0  # CRITICAL: Reset open counter immediately
                    
                    # Log every second
                    if self.closed_frames % FPS == 0:
                        remaining = (TRIGGER_FRAMES - self.closed_frames) / FPS
                        logger.info(f"[EYES_CLOSED] {self.closed_frames/FPS:.0f}s/4s (alarm in {remaining:.0f}s) [score:{closure_score:.4f}]")
                    
                    # TRIGGER at exactly 4 seconds
                    if self.closed_frames == TRIGGER_FRAMES:
                        logger.warning("[ALARM TRIGGERED] Eyes closed 4.0s")
                        self.alarm_on = True
                        self.play_alarm()
                        # Save image when alarm is triggered
                        image_file = self.save_frame(frame, "triggered")
                        self.log_event("ALARM_TRIGGERED", 4.0, closure_score, image_file)
                    
                    # LOOP alarm while eyes closed
                    elif self.alarm_on and self.closed_frames > TRIGGER_FRAMES:
                        if not pygame.mixer.get_busy():
                            self.play_alarm()
                
                else:
                    # EYES ARE OPEN
                    self.open_frames += 1
                    
                    if self.alarm_on:
                        # ALARM IS ACTIVE - CRITICAL: Count down properly
                        if self.open_frames % FPS == 0:
                            remaining = (TRIGGER_FRAMES - self.open_frames) / FPS
                            logger.info(f"[EYES_OPEN] {self.open_frames/FPS:.0f}s/4s (alarm stops in {remaining:.0f}s)")
                        
                        # CRITICAL: Stop after 4 seconds of open eyes
                        if self.open_frames >= TRIGGER_FRAMES:
                            logger.warning("[ALARM STOPPED] Eyes open 4.0s")
                            # Save image when alarm is stopped
                            image_file = self.save_frame(frame, "stopped")
                            self.log_event("ALARM_STOPPED", 4.0, closure_score, image_file)
                            self.stop_alarm()
                            self.alarm_on = False
                            self.closed_frames = 0  # CRITICAL: Reset
                            self.open_frames = 0    # CRITICAL: Reset
                    else:
                        # No alarm - reset closed counter
                        self.closed_frames = 0
                
                # ===== DISPLAY =====
                color = (0, 0, 255) if eyes_closed else (0, 255, 0)
                
                if self.use_pygame_display:
                    try:
                        # Draw rectangle on frame
                        cv2.rectangle(frame, (5, 5), (w-5, h-5), color, 3)
                        
                        y = 35
                        
                        # Status message
                        if self.alarm_on:
                            remaining = (TRIGGER_FRAMES - self.open_frames) / FPS
                            msg = f"ALARM! Eyes open {self.open_frames/FPS:.1f}s/4s (stops {remaining:.1f}s)"
                            cv2.putText(frame, msg, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
                        elif self.closed_frames > 0:
                            remaining = (TRIGGER_FRAMES - self.closed_frames) / FPS
                            msg = f"DANGER! Closed {self.closed_frames/FPS:.1f}s/4s (alarm {remaining:.1f}s)"
                            cv2.putText(frame, msg, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 165, 255), 2)
                        else:
                            cv2.putText(frame, "Status: ALERT", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
                        
                        # Score
                        y += 35
                        cv2.putText(frame, f"Score: {closure_score:.4f} | Threshold: {CLOSED_THRESHOLD:.2f}", 
                                   (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
                        
                        # Convert BGR to RGB for pygame and fix orientation
                        # OpenCV uses (height, width, 3) but pygame surfarray expects (width, height, 3)
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        frame_rgb = np.transpose(frame_rgb, (1, 0, 2))  # Swap width and height
                        frame_surface = pygame.surfarray.make_surface(frame_rgb)
                        
                        # Display frame
                        self.screen.blit(frame_surface, (0, 0))
                        pygame.display.flip()
                        
                        # Check for quit event
                        for event in pygame.event.get():
                            if event.type == pygame.QUIT:
                                logger.info("User quit")
                                running = False
                                break
                            elif event.type == pygame.KEYDOWN:
                                if event.key == pygame.K_q:
                                    logger.info("User quit")
                                    running = False
                                    break
                    except Exception as e:
                        logger.error(f"Display error: {e}")
                else:
                    # Headless mode - use time.sleep to control frame rate
                    time.sleep(0.033)
        
        except Exception as e:
            logger.error(f"Runtime error: {e}", exc_info=True)
        finally:
            self.stop_alarm()
            self.cap.release()
            if self.use_pygame_display:
                try:
                    pygame.quit()
                except Exception as e:
                    logger.error(f"Error closing pygame: {e}")
            try:
                pygame.mixer.quit()
            except:
                pass
            logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        detector = DrowsinessDetector()
        detector.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)


