# Trainer Image

Pre-baked Docker image for Vast.ai YOLO runs. Replaces the per-instance
`apt-get install` + `pip install ultralytics` + `numpy/opencv` reinstall
that used to run on every spin-up (~3-5 min saved).

- Base: `pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime`
- Image: `roothirsch/lego-sorter-training-image:latest`
- Includes: ultralytics, numpy<2, opencv-python-headless, OpenCV apt libs,
  cached YOLO base weights at `/opt/yolo-weights/`.

## Build & publish

```bash
cd software/training/docker
docker login                         # docker hub creds, one time
./build.sh --push                    # cross-builds linux/amd64 + pushes :latest + :YYYYMMDD
```

Without `--push` the script only loads the image into the local Docker
daemon (useful for smoke testing).

Verify on a Vast.ai box:

```bash
vastai create instance <OFFER> \
  --image roothirsch/lego-sorter-training-image:latest \
  --disk 60 --ssh --label trainer-smoke
ssh -p <PORT> root@<HOST> 'python -c "from ultralytics import YOLO; print(YOLO(\"/opt/yolo-weights/yolo26s.pt\").info())"'
```

## When to rebuild

- Ultralytics update broke compat with our checkpoints
- Need a new base weight not in `MODELS` from `tracks/yolo.py`
- CUDA / PyTorch base image bump

After a rebuild the date tag bumps automatically; pin a run by passing
`--image roothirsch/lego-sorter-training-image:YYYYMMDD` to `vastai create
instance` if you want reproducibility.
