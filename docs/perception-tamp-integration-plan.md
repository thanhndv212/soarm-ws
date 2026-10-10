# Camera perception for the SO-101 TAMP loop

Status: research and implementation plan, 2026-09-18. No implementation is implied by this document.

## Goal and first demonstration

Use one fixed USB webcam to locate a known 30 mm cube, pass its measured pose to `soarm_tamp`, plan and execute a pick and place on the physical SO-101, and check the outcome with a new observation. The small ESP32 camera is a later, optional second viewpoint.

The first useful loop is `observe → validate → plan → preflight → execute → verify`. Planning remains inside the HPP container; camera capture and hardware access run on the host. The existing manifest is the handoff between planning and execution. This first loop uses a fiducial marker to establish metric pose with RGB. Markerless detection and scene understanding follow after the complete loop is measured and reliable.

## Current workspace boundary

| Existing component | Current capability | Proposed change |
| --- | --- | --- |
| `camera_calibration/` | Chessboard intrinsics, ArUco generation/detection, Rerun viewing | Add a calibrated camera/board workflow and explicit marker configuration |
| `soarm_tamp/soarm_tamp/plan.py` | Loads a fixed cube pose and records an HPP plan | Accept a validated dynamic scene observation and record its provenance |
| `soarm_tamp/soarm_tamp/config/cube_pick_place.yaml` | Declares object models and initial poses | Keep a default offline pose; measured pose overrides only the cube at plan time |
| `soarm_tamp/soarm_tamp/conventions.py` | Writes/checks a static scene fingerprint | Also check that a live plan corresponds to its observation and calibration |
| `soarm_tamp/soarm_tamp/execute.py` | Streams a recorded manifest and checks calibration, limits, and tracking | Add a pre-execution scene check and a post-execution verification stage; preserve the existing command loop |
| `soarm_sdk/` | Provides URDF-frame arm state, kinematics, limits, and hardware interface | Reuse for robot state; do not put perception algorithms in the hardware SDK |
| `soarm_lerobot/` | Records state/action episodes | Add synchronized camera and pose fields when building a training dataset |

The workspace is a thin repo over independent submodules. Put the initial design and cross-package contract here; make later code changes in the owning submodule. The planning container bind-mounts `soarm-ws`, so a scene JSON file in a run directory can be read on both sides without a new service.

`agimus-ws` is a read-only implementation reference for this effort. It already demonstrates a camera-to-TF-to-object-pose pattern, but SO-ARM currently uses files and a host/container boundary rather than ROS 2 as its runtime contract.

## Decisions to settle before implementation

1. **Object and marker geometry.** The real object is 30 mm per `soarm_tamp/soarm_tamp/geometry.py`. Several comments and the cube initial `z` in `cube_pick_place.yaml` still describe 25 mm and `z = 0.0125`. Reconcile the default pose to the actual 30 mm cube (`z = 0.015` when it rests on the `z = 0` table) and regenerate/check assets before using live observations. Check the generated object geometry and SRDF grasp frame together.
2. **One ArUco dictionary.** `camera_calibration/markers.py` defaults to `DICT_6X6_250`; `detector.py` defaults to `DICT_4X4_50`. Pass a single dictionary explicitly in generation, calibration, and runtime config. Record the printed marker's *physical* black-square edge length in metres; image pixel size is not its metric size.
3. **Marker placement.** A tag on top of a 30 mm cube may be hidden by the gripper. Decide whether the first milestone verifies pick/place with a side tag, a second viewpoint, or a separate object-presence cue. A tag that vanishes during a grasp is an occlusion, not proof of grasp success.
4. **Coordinate frames.** Name transforms by direction. Use `T_base_camera` for camera coordinates into the SO-101 base frame, `T_camera_marker` for marker coordinates into camera coordinates, and a measured rigid `T_marker_object`. Then `T_base_object = T_base_camera @ T_camera_marker @ T_marker_object`. Store quaternions in `xyzw`, positions in metres, and arm joints in SO-101 URDF radians.
5. **Accuracy budget.** The current planner jaw opening is about 36.5 mm around a 30 mm cube: roughly 3.25 mm clearance on each side if perfectly centered. Camera repeatability alone is not sufficient; validate *end-to-end* base-frame pose error against that clearance and the desired grasp margin. If the error budget cannot be met, improve calibration/geometry or add visual alignment before autonomous grasping.

**M0 software status (2026-09-18):** The nominal YAML cube center is now `z = 0.015 m`, the planning jaw is 20°, and regenerated URDF/SRDF assets are checked against the 30 mm cube and grasp frame. The physical cube edge and mass remain approximate; marker size, attachment, and `T_marker_object` are not yet measured. Existing pick-and-place manifests must be replanned.

## Stage 1 — Capture and intrinsic calibration

Use OpenCV `VideoCapture` for the USB webcam, as the existing calibration package already does. Put camera acquisition in a single owner process with a one-frame queue. Timestamp at capture/read, count dropped frames, and discard backlog. Keep the same resolution, focus, and exposure setup for calibration and runtime; store those settings alongside the camera identifier.

Use the existing chessboard calibration first if it produces a good held-out result. Add a ChArUco option when partial views or corner accuracy become a problem. Capture varied board positions and angles across the *actual working area*; a low training reprojection error from nearly identical views is not enough. Save `K`, distortion, resolution, board dimensions, per-view errors, and calibration version in a JSON artifact. Check a held-out board image and undistortion visually in Rerun.

Reuse: `camera_calibration.CameraCalibrator`, OpenCV calibration/ChArUco APIs, and Rerun. Write only the camera-source adapter, metadata checks, and repeatable calibration command. OpenCV recommends ChArUco corners over raw ArUco corners for intrinsic calibration. [OpenCV calibration](https://docs.opencv.org/4.13.0/d4/d94/tutorial_camera_calibration.html), [OpenCV ChArUco](https://docs.opencv.org/5.0/tutorials/objdetect/aruco_calibration/aruco_calibration.html)

**Exit evidence:** reproducible calibration file; held-out reprojection results; no resolution/focus mismatch; recorded images spanning the workspace.

## Stage 2 — Fixed camera to robot-base calibration

Rigidly mount the webcam above or to the side of the table. Place a measured ChArUco/ArUco board in a known SO-101 base-frame location. Use detected 2D corners and their known 3D board coordinates with OpenCV `solvePnP` to estimate the board pose in the camera frame, then derive `T_base_camera`. A multi-marker board gives more correspondences than one small marker and handles partial visibility better. OpenCV's `Board.matchImagePoints()` supplies object/image correspondences for `solvePnP`. [OpenCV Board API](https://docs.opencv.org/4.13.0/d4/db2/classcv_1_1aruco_1_1Board.html), [OpenCV PnP](https://docs.opencv.org/4.13.0/d5/d1f/calib3d_solvePnP.html)

Measure the board-to-base transform independently; otherwise PnP gives a board pose but does not establish where the robot base is. Validate at several table positions with held-out markers and projected fiducials. Save a calibration ID/hash and `T_base_camera` in a versioned JSON artifact. Detect a bumped camera or moved table using fixed reference tags in the view.

Reuse: OpenCV `solvePnP`, `projectPoints`, NumPy/SciPy transforms. Write the frame convention, board placement artifact, and validation checks. If an eye-in-hand camera is added later, OpenCV already has `calibrateHandEye()` and `calibrateRobotWorldHandEye()`; its exact input transform directions must be followed. [OpenCV hand-eye API](https://docs.opencv.org/4.13.0/d2/d75/namespacecv.html)

**Exit evidence:** base-frame test-point error and pose repeatability measured across the intended pick area, plus a deliberate moved-camera test that invalidates the calibration.

## Stage 3 — Detect, estimate pose, and track one tagged cube

Generate a marker using the same dictionary as the detector, print it at a measured size, and rigidly attach it to the cube. Record the marker-to-cube-center transform from physical measurements. OpenCV's `ArucoDetector` returns marker ID and ordered image corners. Estimate `T_camera_marker` with `solvePnP`; `SOLVEPNP_IPPE_SQUARE` is designed for a square with the documented corner order. Use `solvePnPGeneric` when inspecting both planar-pose solutions, then select the physically valid result using reprojection error, table-side constraints, and temporal consistency. [OpenCV ArUco detection](https://docs.opencv.org/4.11.0/d5/dae/tutorial_aruco_detection.html), [OpenCV PnP methods](https://docs.opencv.org/4.13.0/d5/d1f/calib3d_solvePnP.html)

For the first object, marker ID is already the identity. Track pose by comparing consecutive accepted measurements; apply modest smoothing only to reduce jitter. Maintain `DETECTED`, `OCCLUDED`, `STALE`, and `LOST` states. Do not promote a predicted pose to an observed pose or let an old observation silently seed a new plan. Quality gates should include positive camera depth, reprojection error, workspace bounds, jump rate, calibration match, and observation age. Define thresholds from measured data rather than assigning a generic confidence score to OpenCV output.

Reuse: existing ArUco helpers, OpenCV PnP, SciPy rotations. Write the marker-to-object mapping, pose-quality policy, and state transitions.

**Exit evidence:** recorded static and moved-object sequences with detection rate, false ID rate, pose jitter, frame latency, and rejection reasons. Compare estimated cube locations against independently measured positions.

## Stage 4 — Scene contract and recording

Create `soarm_vision/` as an independent optional package. Its smallest useful structure is `sources/`, `detectors/`, `geometry/`, `scene_state.py`, and a CLI such as `soarm-vision snapshot`. Use a versioned Pydantic model or JSON Schema for the host/container file contract:

```json
{
  "schema_version": 1,
  "observation_id": "uuid",
  "camera_id": "webcam_0",
  "calibration_id": "webcam_0_1280x720_v1",
  "base_frame": "so101/base",
  "captured_at_utc": "2026-09-18T12:00:00Z",
  "captured_at_monotonic_ns": 123456789,
  "objects": [{
    "object_id": "cube",
    "status": "DETECTED",
    "pose_xyzquat": [0.22, -0.10, 0.015, 0, 0, 0, 1],
    "reprojection_error_px": 0.5,
    "marker_id": 7,
    "quality": {"accepted": true, "reasons": []}
  }]
}
```

This is an illustrative schema, not a measured observation. Require finite values, a normalized quaternion, known object IDs, an explicit frame, and a matching calibration. Add covariance only after it can be estimated and validated; a placeholder covariance would mislead downstream decisions. Use UTC for durable logs and monotonic time for same-host freshness checks. For cross-machine ESP32 capture, use host receipt time and measured network latency until clock synchronization is demonstrated.

Log camera images, board/marker corners, base-frame pose, error metrics, and arm/plan events to Rerun `.rrd` files. Rerun supports images, 3D transforms, time series, and file plus live sinks. Keep JSON observations as the planner input; Rerun is the replay/debugging record. [Rerun recordings](https://rerun.io/docs/concepts/logging-and-ingestion/recordings), [Rerun Python API](https://ref.rerun.io/docs/python/main/rerun/)

**Exit evidence:** a saved scene snapshot and Rerun recording that can be replayed offline to reproduce every accept/reject decision.

## Stage 5 — Feed perception into HPP planning

Add `--scene <path>` to `soarm_tamp.plan` and pass it through the existing `hpp_container.sh plan` workflow. Validate the observation on the host and again when the container reads it. After `task.setup()` and after applying any measured arm `--start` pose, replace the cube's 7-element free-flyer block in `q_init` with `T_base_object`. Keep the table block and static scene config unchanged. Verify the object order and configuration offsets from the loaded task instead of assuming a hard-coded cube offset; the current task declares six arm joints followed by table and cube free-flyers.

Call `GraspSequencePlanner.plan_sequence()` with this final `q_init`, then record the exact observation, static scene fingerprint, calibration reference, and planned cube pose beside the manifest. The existing `scene.json` fingerprint protects static geometry; the new observation protects the particular *measured* scene used for this plan. Keep the YAML default pose for offline regression and no-camera operation.

Planning needs the SO-101 pose in URDF radians. Capture it with the existing `soarm_tamp.read_pose` path so the first trajectory begins at measured arm state. The camera never supplies robot joint angles.

**Exit evidence:** moving the cube to two distinct reachable spots changes the HPP initial cube pose and planned path; a wrong frame, malformed quaternion, stale observation, or unreachable pose is refused before execution.

## Stage 6 — Preflight, execute, and visual verification

Before live execution, obtain a *new* camera observation and compare it to the pose in the plan. This is necessary because HPP planning can take long enough for a previously fresh snapshot to become old. Measure both translation and rotation differences using the object's symmetries; a visually identical cube rotation may be equivalent for the selected grasp. Refuse to start when the cube has moved outside the measured grasp tolerance or has been lost. Continue the existing calibration, servo-limit, scene-fingerprint, and waypoint checks.

Execute the recorded manifest through `soarm_tamp.execute`, preserving its hardware polling and synchronization behavior. Observe again at a meaningful phase boundary and after place. For the first demonstration, an explicit stop and operator confirmation of the grip is acceptable if the overhead tag is occluded. A later side/second camera can establish autonomous grip verification. Re-detecting the cube at the final location tests placement; a single missing tag does not prove success or failure.

The current executor derives jaw actions from segment labels and edge names. Phase-level visual checks must be attached to verified segment semantics, not arbitrary array indices. Start with a full planned sequence and pre/post checks. Split planning/execution by phase only after the manifest carries explicit phase boundaries and held-object state, so HPP's continuity and attachment assumptions can be reconstructed correctly.

**Exit evidence:** the robot does not move after deliberate object displacement or camera loss; a completed run records final translation/orientation error and a clear `SUCCESS`, `RETRYABLE_FAILURE`, or `ABORT` result.

## Stage 7 — Continuous service and mission orchestration

The first integration can use the shared run-directory JSON file. When multiple consumers need live state, add a host `visiond` process. PyZMQ is a small optional choice for latest observations (`PUB/SUB`) and explicit snapshot requests (`REQ/REP`); bound queues and discard stale messages. Avoid coupling the 30 Hz servo command loop to camera capture, inference, network, or viewer repaint. [PyZMQ guide](https://pyzmq.readthedocs.io/en/latest/howto/index.html)

Add a host mission runner with explicit transitions: `OBSERVE → VALIDATE → PLAN → PREFLIGHT → EXECUTE → VERIFY → COMPLETE/REPLAN/ABORT`. Begin with one object and one pick/place. On uncertainty, stop and ask for a new observation; on a valid moved-object pose, replan. Keep retry count and reason in the run log. A behavior tree becomes useful once there are several reusable tasks and recovery branches; it need not be the first runtime dependency.

**Exit evidence:** test runs for camera disconnect, occlusion, moved object during planning, unreachable object, failed grasp, and successful retry, with no unbounded queue growth or duplicate hardware-bus owner.

## Stage 8 — ESP32 second camera and richer perception

For an ESP32 camera, reuse Espressif's HTTP camera server and begin with still JPEG snapshots. Add a `CameraSource` adapter with timeout, reconnect, host receive timestamp, and measured request latency. Calibrate this camera separately at its configured resolution. Fuse the second view only after its extrinsic transform and temporal skew have been measured. Its initial role should be side-view grip/placement verification or coarse object presence. [ESP-IDF HTTP server](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/protocols/esp_http_server.html)

For markerless detection, first try known-size objects on the known table: an instance mask or keypoints plus geometric pose estimation. A 2D bounding box or segmentation mask alone does not provide metric 6D pose. For multiple objects, established tracking packages such as ByteTrack/BoT-SORT can supply IDs; Ultralytics exposes both, but its AGPL/enterprise licensing needs review before it is adopted as an MIT workspace dependency. [Ultralytics tracking](https://docs.ultralytics.com/modes/track/), [Ultralytics licensing](https://github.com/ultralytics/ultralytics/blob/main/CONTRIBUTING.md)

For a harder 6D-pose problem, evaluate an RGB-D camera and FoundationPose against recorded SO-101 tabletop scenes. RealSense has Python RGB/depth streaming, alignment, and deprojection; FoundationPose offers model-based pose estimation and tracking, with an NVIDIA Isaac ROS integration. Treat it as an optional GPU deployment. SAM 2 can propagate masks in video, but it still needs a metric pose estimator before its result enters HPP. [RealSense Python SDK](https://realsenseai.github.io/librealsense/python_docs/), [FoundationPose](https://github.com/NVlabs/FoundationPose), [Isaac ROS pose estimation](https://nvidia-isaac-ros.github.io/v/release-3.2/repositories_and_packages/isaac_ros_pose_estimation/index.html), [SAM 2](https://github.com/Segment-Anything/segment-anything-2)

If grasp positions become variable, generate candidate grasp frames from the object's model or a learned proposer, then check them with HPP IK and collision constraints before they are used. That is separate from detecting an object's pose.

## Stage 9 — Dataset and evaluation

Store diagnostic runs in Rerun, including raw frames, estimates, rejected candidates, calibration IDs, arm state, planned/commanded motion, and outcomes. Extend `soarm_lerobot` only when synchronized camera data will be used for learning. LeRobotDataset v3 supports multi-camera video alongside state/action data and episode metadata. Keep the exact `lerobot` version pinned when extending the recorder because the workspace's current feature schema is minimal. [LeRobotDataset v3](https://huggingface.co/docs/lerobot/lerobot-dataset-v3)

For markerless 6D-pose comparisons, use BOP Toolkit's pose-error and dataset conventions instead of inventing a new benchmark. Local task metrics still matter: pick success, placement error, false accepts, scene rejection rate, detection latency, recovery success, and time from observation to motion. [BOP Toolkit](https://github.com/thodan/bop_toolkit)

## Practical delivery order

| Milestone | Deliverable | Gate before continuing |
| --- | --- | --- |
| M0 | Reconcile 30 mm cube model, `z`, assets, and ArUco dictionary | Geometry and marker configuration agree end to end |
| M1 | USB webcam calibration plus fixed `T_base_camera` | Held-out workspace error fits the grasp accuracy budget |
| M2 | Tagged-cube `SceneObservation` plus Rerun record | Repeated pose/latency benchmark and rejection reasons available |
| M3 | `plan --scene` and manifest provenance | HPP plans change with measured cube position; malformed/stale inputs fail |
| M4 | Pre-execution reobserve and post-execution verification | Moved/lost cube prevents motion; final result is recorded |
| M5 | Mission runner and recovery | Failure-injection scenarios stop or replan correctly |
| M6 | ESP32 side view, markerless tracking, RGB-D/6D pose as needed | Each adapter meets the same scene contract and measured task metrics |

The first implementation should finish M0–M4 before adding a model server or a new robot middleware. The choice to add visual servoing depends on the measured error relative to the jaw clearance, not on detector benchmark accuracy alone.
