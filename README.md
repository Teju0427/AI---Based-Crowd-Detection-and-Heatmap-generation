# 🎯 Real-Time Crowd Detection & Heatmap Generation

## 📌 Project Overview

This project focuses on **real-time crowd detection and analysis** using a trained deep learning model. It detects people in live video streams and generates **heatmaps** to visualize crowd density and movement patterns.

The system can be used for:

* Public safety monitoring
* Crowd management
* Smart surveillance systems

---

## 🚀 Features

* 🎥 Real-time crowd detection using video/webcam
* 📦 Pre-trained custom model (`best.pt`)
* 🔥 Heatmap generation for crowd density visualization
* 📊 Detection on recorded video
* ⚡ Fast and efficient processing

---

## 🧠 Model Details

* Model Used: YOLO-based object detection
* Task: Person detection
* Output:

  * Bounding boxes around people
  * Heatmap showing crowded regions

---

## 📂 Project Structure

```
real-time-crowd-detection/
│
├── camera_test.py          # Real-time webcam detection
├── realtime_detect.py      # Detection on video
├── best.pt                 # Trained model
├── runs/                   # Training results 
├── sample_video.mp4        # Sample output video
├── README.md
```

---

## 📊 Dataset

The dataset used for training is available here:

👉 [Download Dataset](PASTE_YOUR_GOOGLE_DRIVE_LINK_HERE)

---

## 🎬 Sample Output

A sample output video demonstrating detection and heatmap:

👉 [Watch Sample Video](PASTE_YOUR_VIDEO_LINK_HERE)

---

## ⚙️ How to Run

### 1. Install Dependencies

```
pip install opencv-python torch ultralytics
```

### 2. Run Real-Time Detection

```
python camera_test.py
```

### 3. Run Detection on Video

```
python realtime_detect.py
```

---

## 🔥 Heatmap Generation

The system generates heatmaps by:

* Tracking detected people across frames
* Accumulating their positions
* Highlighting high-density areas

This helps in identifying:

* Crowded zones
* Movement patterns
* High traffic regions

---

## 🖼️ Output

* Bounding boxes on detected people
* Real-time video processing
* Heatmap overlay on frames

---

## 🎓 Applications

* Smart city surveillance
* Event crowd monitoring
* Traffic and pedestrian analysis
* Safety and security systems

---

## 📌 Conclusion

This project demonstrates how AI can be used for **real-time crowd monitoring and analysis**. The integration of detection and heatmaps provides deeper insights into crowd behavior.

---

## 🙋‍♀️ Author

**Tejaswini**
Computer Science Student 💻
