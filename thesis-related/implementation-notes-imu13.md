# IMU 1.3 Implementation Notes

**Date:** 2026-03-21
**Scope:** `IMUManager.swift` (full rewrite) + `AppViewModel.swift` (integration)

---

## What Was Built

IMU Channel as specified in Path B Layer 1 — binary motion state detection using raw accelerometer data, with dual role as a capture trigger and a frame metadata tag.

---

## IMUManager.swift

### Sensor source

Switched from `CMDeviceMotion` (sensor-fused, gravity-compensated) to `CMAccelerometer` (raw). Rationale: the device is body-mounted in an unknown orientation, so the attitude reference frame of `CMDeviceMotion` is not meaningful, and `CMMotionActivityManager`'s classifier assumptions (phone in pocket/hand) do not apply.

### Processing pipeline (50 Hz)

1. Each sample: compute composite magnitude `√(ax² + ay² + az²)` (includes gravity component, ~1 g at rest)
2. Maintain a 2.5 s rolling window — 125 samples at 50 Hz
3. Compute sample variance over the window

### State machine

Serialised on a dedicated `stateQueue` (serial `DispatchQueue`).

| Condition | Action |
|---|---|
| `variance > 0.012 g²` | Start or continue the sustained-motion clock |
| Clock ≥ 6 s | Transition → `sustained_motion` |
| `variance < 0.006 g²` | Reset clock, transition → `stationary` |
| Between thresholds | No change (hysteresis zone — transient spikes absorbed) |

Thresholds are conservative starting values; expected to be tuned during the study.

The 6 s sustained-motion threshold sits in the middle of the 5–8 s range specified in the PRD. It can be adjusted via `AppViewModel.sustainedMotionThreshold` (already a persisted `@Published` property).

### Outputs

- `currentMotionState: MotionState` — `.stationary` | `.sustained_motion`
- `onMotionStateChanged: ((MotionState) -> Void)?` — dispatched to **main thread** on every transition
- `imuTags: [String: Any]` — `{ "motion_state": "stationary" | "sustained_motion" }`, thread-safe via `stateQueue.sync`
- CSV log: `imu_accelerometer.csv` — columns: `timestamp, accelX, accelY, accelZ, magnitude`

### Thread safety

- Window append and state computation are both serialised through `stateQueue`
- `imuTags` reads `currentMotionState` inside `stateQueue.sync` so it is safe to call from any thread (e.g., `StreamServer` background thread building the status response)
- `onMotionStateChanged` is always dispatched to `DispatchQueue.main` before firing

---

## AppViewModel.swift Integration

### New published property

```swift
@Published var motionState: MotionState = .stationary
```

Reflects the current IMU state for SwiftUI views and the web UI.

### Lifecycle

`IMUManager` is instantiated directly in `AppViewModel` (independent of `AIAnalysisManager`). It follows recording lifecycle:

| Recording event | IMU action |
|---|---|
| `startRecording()` | `imuManager.start(dataDirectory:)` |
| `stopRecording()` | `imuManager.stop()` |
| `pauseRecording()` | `imuManager.stop()` |
| `resumeRecording()` | `imuManager.start(dataDirectory:)` — same session directory, data appends |

### Session directory

Data is written to:

```
Documents/Sessions/<ISO8601-recording-start-time>/imu_accelerometer.csv
```

`recordingStartTime` is reused across pause/resume so that resume appends to the same file rather than creating a new one.

### Status endpoint

`imu_tags` is included in the dict returned by the `onStatus` callback (served at `/status` by `StreamServer`):

```json
{
  "imu_tags": { "motion_state": "stationary" }
}
```

### Trigger hook

`handleMotionStateTransition(_:)` is called on the main thread on every transition. Currently it logs the event and notes `captureMinInterval`. Layer 1.5 can observe `AppViewModel.motionState` directly (it is `@Published`) to drive adaptive capture scheduling.

---

## Not Implemented (by design)

- Activity classification — excluded per spec. The VLM determines specific activity (walking, cycling, cooking) from the visual frame. The IMU only answers "moving or not."
- `CMMotionActivityManager` — excluded. Classifier assumptions mismatch body-mounted posture.
- Passing `sustainedMotionThreshold` from `AppViewModel` into `IMUManager` at runtime — the threshold is currently hardcoded to `6.0 s` in `IMUManager`. Wiring the user-configurable `sustainedMotionThreshold` property into the manager is a straightforward follow-up if needed.
