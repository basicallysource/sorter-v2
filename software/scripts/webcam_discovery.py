import cv2
import numpy as np
import sys

MAX_INDEX = 10
TILE_WIDTH = 320
TILE_HEIGHT = 240

def main():
    caps = []
    for i in range(MAX_INDEX):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                caps.append((i, cap))
                continue
        cap.release()

    if not caps:
        print("no webcams found")
        sys.exit(1)

    print(f"found {len(caps)} webcam(s): {[i for i, _ in caps]}")
    print("press q to quit")

    cols = min(len(caps), 3)
    rows = (len(caps) + cols - 1) // cols

    while True:
        tiles = []
        for idx, cap in caps:
            ret, frame = cap.read()
            if not ret:
                frame = np.zeros((TILE_HEIGHT, TILE_WIDTH, 3), dtype=np.uint8)
            frame = cv2.resize(frame, (TILE_WIDTH, TILE_HEIGHT))
            label = f"index {idx}"
            cv2.putText(frame, label, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 5)
            cv2.putText(frame, label, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2)
            tiles.append(frame)

        # pad to fill grid
        while len(tiles) % cols != 0:
            tiles.append(np.zeros((TILE_HEIGHT, TILE_WIDTH, 3), dtype=np.uint8))

        row_imgs = []
        for r in range(rows):
            row_imgs.append(np.hstack(tiles[r * cols : r * cols + cols]))
        grid = np.vstack(row_imgs)

        cv2.imshow("webcam discovery", grid)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    for _, cap in caps:
        cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
