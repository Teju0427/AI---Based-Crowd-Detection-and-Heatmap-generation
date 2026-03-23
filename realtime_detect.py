import cv2
from ultralytics import YOLO

model = YOLO("best.pt")

cap = cv2.VideoCapture(1)

while True:

    ret, frame = cap.read()

    if not ret:
        print("Camera not detected")
        break

    results = model(frame)

    people_count = 0

    for r in results:
        for box in r.boxes:
            cls = int(box.cls)

            if cls == 0:
                people_count += 1

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame,(x1,y1),(x2,y2),(0,255,0),2)

    cv2.putText(frame,f"People: {people_count}",
                (20,40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,(0,0,255),2)

    cv2.imshow("Crowd Detection",frame)

    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()