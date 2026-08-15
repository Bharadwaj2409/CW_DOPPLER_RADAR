# Doppler RADAR with Multi-Target Tracking

A real-time Doppler RADAR project built using GNU Radio, SDR hardware and Python, with CA-CFAR based target detection, UDP communication and a custom PyQt5 RADAR GUI.

This started off as a fairly simple Doppler RADAR setup — receive the signal, extract the Doppler shift and calculate target velocity. Over time, I kept adding to it and the project has now evolved into a multi-target detection and tracking system capable of detecting and displaying up to five targets in real time.

The main focus of this project has been getting the complete chain working properly, from the received RF signal all the way to a usable RADAR display.

## Current Architecture

```text
RF / SDR
   │
   ▼
GNU Radio
   │
   ├── Filtering
   ├── FFT / Doppler Processing
   ├── Velocity Estimation
   └── CA-CFAR
          │
          ▼
   Target Detections
          │
          ▼
     UDP Transfer
          │
          ▼
 Multi-Target Tracker
          │
          ▼
     PyQt5 GUI
```

## How the project evolved

### 1. Basic Doppler RADAR

The first version was mainly about getting reliable Doppler information from the received signal.

The GNU Radio flowgraph handled the incoming samples, filtering and spectral processing. From the detected Doppler frequency, radial velocity could then be calculated.

At this point the basic chain was:

```text
RX Signal → Filtering → FFT → Doppler Frequency → Velocity
```

This gave me a working base to build the rest of the system around.

### 2. Building the RADAR GUI

Once the Doppler and velocity outputs were working, I built a custom RADAR GUI in Python using PyQt5.

The GUI started as a single-target display with:

* configurable RADAR sector
* animated sweep
* range rings
* detection threshold
* Doppler and velocity readout
* signal level display
* target blip animation
* configurable velocity scaling
* target lifetime and fade-out

The target position on the display is driven by its velocity rather than being a random animation.

The convention currently used is:

```text
Positive velocity → Approaching → Moves towards RADAR centre
Negative velocity → Receding   → Moves away from RADAR centre
```

Getting this right required correcting the original velocity-to-radius mapping in the GUI.

### 3. GNU Radio to GUI over UDP

I wanted the signal processing and GUI to remain separate instead of putting everything into one Python application.

The GNU Radio side therefore sends the detected target information to the GUI using UDP.

Each target detection contains three `float32` values:

```text
Doppler Frequency (Hz)
Velocity (m/s)
Signal Level (dBFS)
```

So each detection is a 12-byte binary vector:

```text
| Doppler float32 | Velocity float32 | Signal float32 |
```

The PyQt5 application runs its own UDP receiver thread, decodes the incoming vectors and passes them to the tracking/display logic.

This also means the GUI does not need to know how the actual RADAR DSP is being implemented. As long as it receives the expected UDP format, the processing side can be changed independently.

## CA-CFAR Detection

A fixed signal threshold works for initial testing, but it isn't enough once the noise floor starts changing.

CA-CFAR was therefore added to the Doppler processing chain.

The detector estimates the local noise level using training cells around the Cell Under Test while excluding nearby guard cells.

```text
Training | Guard | CUT | Guard | Training
                     │
                     ▼
               CFAR Decision
```

The current processing also uses minimum peak separation and an additional signal/SNR requirement to reduce detections caused by noise.

CFAR parameters have been adjusted during testing as false targets showed up in the multi-target version.

## Moving to Multiple Targets

The original system only cared about the strongest target.

That became a limitation pretty quickly, so the processing and UDP implementation were modified to handle multiple detections from the same processing interval.

The current system supports up to **five simultaneous targets**.

This required changes on both sides.

On the GNU Radio side:

* detect multiple valid Doppler peaks
* apply CFAR independently to candidate peaks
* reject weak/noisy peaks
* maintain minimum separation between detections
* send multiple target vectors over UDP

On the GUI side:

* parse multiple detections from each UDP packet
* maintain multiple target tracks
* associate new detections with existing tracks
* create new tracks when required
* independently remove stale tracks
* display up to five targets

## Multi-Target Tracking

Simply finding five FFT peaks and drawing five triangles wasn't enough.

Without tracking, noise peaks or slight changes in Doppler could continuously create new targets. A single physical target could also end up appearing as multiple targets.

I added basic track association using both Doppler and velocity.

For every new detection, the GUI compares it against the existing tracks using:

```text
Δ Doppler
Δ Velocity
```

If both are within the configured gates, the existing track is updated.

Otherwise, the detection becomes a candidate for a new track.

The GUI currently exposes parameters for:

* Doppler matching gate
* velocity matching gate
* track timeout
* blip lifetime
* detection threshold

This made the display considerably more stable than simply drawing every CFAR output.

## False Target Rejection

This became especially important after moving to multi-target detection.

The first multi-target implementation would occasionally show two or three targets even when they weren't actually present.

There were a few things contributing to this.

One issue was that an older single-target processing block and the newer multi-target block could both feed the UDP path. That was removed so there is now only one multi-target detection path producing the target data.

The CFAR settings were also made more conservative.

The current processing uses tighter values for:

* training cells
* guard cells
* probability of false alarm
* minimum peak separation
* SNR / detection threshold

The GUI also doesn't immediately trust every single detection anymore.

A new detection first has to behave like a real target before it is treated as a confirmed track.

Conceptually:

```text
Detection
    │
    ▼
Candidate Track
    │
    ▼
Detected Again?
   / \
 No   Yes
 │     │
Reject │
       ▼
 Confirmed Target
```

This helps remove isolated CFAR hits and random FFT peaks without making the actual target display excessively slow.

Duplicate-track suppression and track timeouts are also used so that old or closely spaced detections don't keep appearing as separate targets.

## Current Processing Chain

At this stage the project looks roughly like this:

```text
SDR / RF Input
      │
      ▼
GNU Radio
      │
      ▼
Filtering
      │
      ▼
Doppler FFT
      │
      ▼
CA-CFAR
      │
      ▼
Peak Detection
      │
      ▼
Velocity Calculation
      │
      ▼
Multiple Target Candidates
      │
      ▼
UDP
      │
      ▼
Detection Association
      │
      ▼
Track Confirmation
      │
      ▼
Multi-Target RADAR GUI
```

## GUI

The current GUI can display up to five tracked targets and provides controls for most of the parameters that I found useful while testing.

Current features include:

* up to 5 simultaneous targets
* configurable RADAR sector
* animated RADAR sweep
* Doppler frequency display
* radial velocity display
* received signal level
* configurable detection threshold
* velocity scaling
* Doppler association gate
* velocity association gate
* track timeout
* target persistence
* target fade-out
* UDP connection controls
* live target count

The GUI is written in Python/PyQt5 and is intended to run independently from GNU Radio.

## UDP Packet Format

The current UDP target format is deliberately simple.

Each detection consists of:

| Value             | Type      |    Size |
| ----------------- | --------- | ------: |
| Doppler Frequency | `float32` | 4 bytes |
| Velocity          | `float32` | 4 bytes |
| Signal Level      | `float32` | 4 bytes |

Total:

```text
12 bytes / target
```

A packet can contain multiple consecutive target vectors.

The receiver therefore interprets the packet as:

```text
Target 1: Doppler | Velocity | Signal
Target 2: Doppler | Velocity | Signal
Target 3: Doppler | Velocity | Signal
...
```

This keeps the GNU Radio → GUI interface lightweight and easy to debug.

The repository will continue changing as the RADAR processing and tracking are improved.

## What has been implemented so far

* Doppler RADAR signal processing
* FFT-based Doppler extraction
* radial velocity calculation
* GNU Radio implementation
* CA-CFAR target detection
* multiple Doppler peak detection
* binary UDP target transport
* Python UDP receiver
* PyQt5 RADAR GUI
* single-target visualization
* multi-target visualization
* tracking of up to five targets
* Doppler/velocity based data association
* target confirmation
* track timeout and deletion
* duplicate/false-target suppression
* configurable detection and tracking parameters

## Next Steps

There is still plenty I want to do with this.

The biggest next step is moving beyond a Doppler-only system and adding proper range information.

That opens the door to:

* Range-Doppler Maps
* 2D CFAR
* range + velocity target association
* Kalman filtering
* better track initiation/deletion logic
* angle estimation
* target trajectories
* target classification
* FPGA acceleration
* Zynq/SoC implementation

Eventually, I want the processing chain to move closer to:

```text
RF
 │
 ▼
ADC / SDR
 │
 ▼
Range + Doppler Processing
 │
 ▼
Range-Doppler Map
 │
 ▼
2D CFAR
 │
 ▼
Target Detection
 │
 ▼
Data Association
 │
 ▼
Multi-Target Tracking
 │
 ▼
RADAR GUI
```

## Tools / Technologies

**RADAR & DSP**

`Doppler Processing` · `FFT` · `CA-CFAR` · `Peak Detection` · `Velocity Estimation` · `Multi-Target Tracking`

**Software**

`GNU Radio` · `Python` · `PyQt5` · `Linux`

**Communication**

`UDP` · `Binary float32 data`

**Hardware**

`SDR` · `RF Front-End` · `Raspberry Pi`

---

This is still an actively developing project. A lot of the work so far has been iterative — build something, test it on the actual RADAR chain, find what breaks or gives bad detections, fix it, and then build the next part on top of it.

The end goal is to keep pushing it from a basic Doppler demonstration towards a proper real-time RADAR detection and multi-target tracking platform.
