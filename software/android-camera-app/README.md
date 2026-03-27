# Android Camera App

Small dedicated Android camera app for the LEGO sorter.

It runs on Android 11+ and exposes:

- `GET /video` for an MJPEG stream
- `GET /snapshot.jpg` for the latest still image
- `GET /health` for a tiny JSON health response

The sorter can consume it through the existing URL-based camera support.

When the stream is running, the app also advertises itself over mDNS/Bonjour as a
`_legosorter-camera._tcp` service so the sorter UI can auto-discover it on the local network.
If the phone is connected over USB with `adb`, the sorter backend can also surface it automatically
through an ADB-forwarded local URL.

## Build

From `software/android-camera-app`:

```bash
./gradlew assembleDebug
```

## Install

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Use Over USB

1. Open the app on the phone. It auto-starts the stream once camera permission is granted.
2. Forward the device port to the Mac:

```bash
adb forward tcp:8080 tcp:8080
```

3. Point the sorter camera role at:

```text
http://127.0.0.1:8080/video
```

Snapshot endpoint:

```text
http://127.0.0.1:8080/snapshot.jpg
```

## Use On The Network

1. Put the phone and sorter Mac on the same local network.
2. Open the app and leave streaming enabled.
3. In the sorter settings camera picker, use `Refresh Cameras`.
4. The phone should appear under `Discovered Android Cameras`.

## Notes

- The app keeps the screen awake while open.
- The default port is `8080`.
- Front/back camera can be switched in the app.
- This project intentionally lives in its own folder so it can evolve independently from the sorter UI/backend.
