# GamingForce Z / Royal Kludge G87 RGB keyboard protocol

This document describes the configuration protocol of the keyboard. It was
reconstructed by analysing the vendor tool (`RK G87 RGB Keyboard`, version
`V1.00.215n`, modules `GamingKeyboardWriter.dll` and `SonixHidDll.dll`) and by
testing against a real keyboard (firmware 1.01, USB `05AC:024F`).

Every statement carries a confidence level:

| Label | Meaning |
|---|---|
| **[confirmed]** | exercised on a keyboard with `g87ctl` |
| **[from driver]** | read from the vendor code, not yet sent to a keyboard |
| **[unknown]** | the command exists in the vendor code, its effect is not established |

## 1. Device

Controller: SONiX. The vendor tool knows two USB id pairs (stored as string
resources `0x4268` / `0x4269` of `GamingKeyboardWriter.dll`):

| VID:PID | Notes |
|---|---|
| `0C45:7A04` | first build of the tool (a genuine SONiX id) |
| `05AC:024F` | later build; the keyboard poses as an Apple keyboard |

**Warning:** `05AC:024F` is reported by many unrelated SONiX based keyboards
(some Keychron and other Royal Kludge models among them). The USB id alone does
not identify a G87 - run the check from section 4.3 before writing anything.

HID interfaces **[confirmed]**:

| Interface | Collection | Role |
|---|---|---|
| 0 | boot keyboard (usage `01/06`) | 64 byte feature report without a report id - **the configuration channel** |
| 1 | consumer control, report `03` | media keys |
| 1 | system control, report `02` | power / sleep |
| 1 | mouse, report `06` | mouse functions assigned to keys |
| 1 | NKRO keyboard, report `01` | 120 bit key bitmap |
| 1 | vendor `FFFF/01`, report `05` | 3 byte notifications to the host tool (section 7) |

The configuration channel is feature `SET_REPORT` / `GET_REPORT` on interface 0
(`HidD_SetFeature` / `HidD_GetFeature`, 65 byte buffer: a `00` byte followed by
64 data bytes). Windows opens the keyboard interface exclusively, but feature
reports still work on a handle opened without read or write access
(`dwDesiredAccess = 0`).

## 2. Command packet

All packets are 64 bytes long. A command looks like this:

```
byte 0      04              fixed prefix
byte 1      opcode
byte 2      00
byte 3      status          00 in the request
bytes 4-7   00 / result     in the answer to 04 02: checksum (u32 LE)
bytes 8-9   number of data packets (u16 LE)
bytes 10+   00
```

After taking a command the keyboard exposes its echo in the feature report,
with a status byte:

| Status | Meaning |
|---|---|
| `00` | not processed yet |
| `01` | accepted |
| `FF` | error (for example a command in the wrong transaction state) |

## 3. Transactions

### 3.1 Writing a block **[confirmed]**

1. Send `04 <opcode>` with the packet count in bytes 8-9.
2. Leave time for the flash erase: the vendor tool waits
   `35 ms x ceil(size / 512)`, then reads the report and requires status `01`
   (up to 5 attempts).
3. Send the data in 64 byte packets (the last one zero padded), 10 ms apart.
4. Send `04 02`. The keyboard answers `04 02 00 01 <sum u32 LE>`, where the sum
   is the plain arithmetic sum of all data bytes from step 3. A mismatch means
   a transmission error.

Example (lighting write, 18 packets):

```
-> 04 13 00 00 00 00 00 00 12 00 ...
<- 04 13 00 01 00 00 00 00 12 00 ...
-> 18 data packets
-> 04 02 00 00 ...
<- 04 02 00 01 ca 82 00 00 ...        sum = 0x82ca
```

### 3.2 Reading a block **[confirmed]**

1. Send `04 05` with the packet count (2).
2. Each following `GET_REPORT` returns one data packet.
3. `04 02` returns the sum of the data that was read.

**Where the firmware differs from what the vendor tool expects:** firmware 1.01
shows the acknowledgement `04 05 00 01` for well under a millisecond and then
replaces the report with the first data packet. The vendor tool waits 10 ms
before looking for the acknowledgement, finds data instead (byte 3 is `00`)
and counts the attempt as failed. A transaction must always be closed with
`04 02`; otherwise the next command is answered with status `FF`. This is the
likely source of the error messages the vendor tool shows.

## 4. Command list

| Opcode | Direction | Data | Description | Confidence |
|---|---|---|---|---|
| `04 02` | - | - | end of transaction, returns the checksum | confirmed |
| `04 05` | read | 2 packets | device information block | confirmed |
| `04 11` | write | 10 packets (0x280) | key map | from driver |
| `04 13` | write | 18 packets (0x480) | lighting | confirmed |
| `04 15` | write | variable | macros | from driver |
| `04 17` | write | 1 packet | profile summary / gaming mode | confirmed |
| `04 18` | - | - | sent with a boolean "true", expects an acknowledgement | unknown |
| `04 19` | - | - | counterpart of `04 18` (boolean "false") | unknown |
| `04 AB` | write | 1 packet | firmware authenticity check | confirmed |
| `04 E0` | - | - | "are you alive" - only acknowledged | confirmed |
| `04 F0` | - | - | sent after a lighting write, never acknowledged | confirmed (sending), effect unknown |
| `04 F1` | - | - | counterpart of `04 F0`, never acknowledged | unknown |

The vendor tool contains no command that reads the stored configuration (key
map, lighting, macros). `04 05` is the only read. The tool keeps the state in a
local SQLite database and always sends whole blocks.

Hypotheses for the unknown commands (to be verified): `04 18` / `04 19` enter
and leave an editing mode (the tool's configuration mentions
`CloseCustomizeMode`); `04 F0` / `04 F1` end and start host controlled LED mode
(modules `LEDSimulator`, `GamingForceLEDSyncer`). Opcodes outside this table
have not been tried: an unknown command may erase part of the flash before any
data arrives.

All of them can be sent with `g87ctl experimental` (see the README).

### 4.1 Call order in the vendor tool

Before every write the tool looks the device up, runs `04 AB` (the check) and
then does the write. "Apply all" is, in order: `04 11`, `04 13` + `04 F0`,
`04 17`, `04 15`.

### 4.2 Information block (`04 05`) **[confirmed]**

128 bytes. Contents on the tested keyboard:
`40 30 00 00 ac 05 4f 02 01 01 ff ff 00 ...`

| Offset | Size | Meaning |
|---|---|---|
| 0 | 1 | `40` - not established (packet size?) |
| 1 | 2 | macro memory capacity in 64 byte packets (`0x0030` = 3072 bytes); used by the vendor tool |
| 4 | 2 | VID |
| 6 | 2 | PID |
| 8 | 2 | firmware version (`01 01` = 1.01) - presumed |
| 10 | 2 | `ff ff` - not established |

### 4.3 Authenticity check (`04 AB`) **[confirmed]**

The host sends `04 AB`, waits for the acknowledgement, sends one packet of 64
random bytes `r[0..63]` and then `04 02`. Instead of a checksum the keyboard
returns:

```
b3 = (r[0x0C] + r[0x03]) & 0xFF
b2 = (r[0x3F] << 3) & 0xFF
b1 = (r[0x06] - r[0x0D]) & 0xFF
b0 =  r[0x24] & 0xA5
result = ((b3 << 24) | (b2 << 16) | (b1 << 8) | b0) XOR 0x54711688
```

This tells the host that the expected firmware is on the other end. `g87ctl`
requires a correct result before every write. Whether the firmware itself
needs the check before it accepts a write has not been established.

## 5. Lighting block (`04 13`) **[confirmed]**

0x480 bytes:

| Offset | Size | Contents |
|---|---|---|
| 0x000 | 32 x 16 | effect records (slots 0-31) |
| 0x200 | 144 x 4 | key colours of the custom mode, 8 x 18 matrix |
| 0x440 | 16 | copy of the record of the **active** effect |
| 0x450 | 0x30 | zeros (padding) |

### 5.1 Effect record (16 bytes)

| Offset | Meaning |
|---|---|
| 0 | effect number: 1-19 built-in effects, `0x80` custom mode |
| 1-3 | colour R, G, B |
| 4-7 | 0 |
| 8 | 1 = full palette ("Full Color"), 0 = single colour |
| 9 | brightness 1-16 |
| 10 | speed 1-16 |
| 11 | direction 0-3 |
| 12-13 | 0 |
| 14-15 | `aa 55` |

Slot `n - 1` holds effect `n`. Slot 19 is the custom mode:
`80 00 ... [9] = brightness ... aa 55`. Slots 20-31 are zero.

Effects (names from the vendor tool's UI):

| No | Name | No | Name | No | Name |
|---|---|---|---|---|---|
| 1 | Static | 8 | Spectrum | 15 | Ripples |
| 2 | SingleOn | 9 | Outward | 16 | Flowing |
| 3 | SingleOff | 10 | Scrolling | 17 | Pulsating |
| 4 | Glittering | 11 | Rolling | 18 | Tilt |
| 5 | Falling | 12 | Rotating | 19 | Shuttle |
| 6 | Colourful | 13 | Explode | 0x80 | UserDefine |
| 7 | Breath | 14 | Launch | | |

The vendor tool has a table for 32 generic effects (`LightingMode_1` ...
`LightingMode_32`) while its configuration enables 19. Numbers 20-32 are
candidate **hidden effects** of the firmware; `g87ctl experimental effect N`
sends a record with such a number.

Before sending, the vendor tool substitutes three exact colours (LED
correction): `#0096ff -> #40b0ff`, `#0000ff -> #3080ff`, `#000096 -> #3030ff`.

The vendor database stores brightness and speed as slider positions 0-15; on
the wire they are 1-16. What a value of 0 does has not been tested.

### 5.2 Key colours

Each entry is 4 bytes: `80 R G B`. Entry index = `row x 18 + column`. Key
positions (row_column) come from the tool's `KeyboardIDMapping.xml`, for
example `Esc = 0_1`, `F1 = 0_2`, `` ` `` = 1_1, `Tab = 2_1`, `Caps Lock = 3_1`,
`Left Shift = 4_1`, `Left Ctrl = 5_1`, `Space = 5_4`, `Print Scr = 6_4`,
`Insert = 6_8`, `Up = 5_11`. The full table is in `g87ctl/keys.py`. The mapping
of positions to physical keys is **[from driver]** and still needs visual
confirmation.

## 6. Other blocks

### 6.1 Profile summary (`04 17`), 64 bytes

| Offset | Meaning | Confidence |
|---|---|---|
| 0 | light mode number from the vendor database, clamped to 10 (9 = effect 1, anything later = 10) | confirmed (write) |
| 1 | gaming mode enabled (0/1) | from driver |
| 2-4 | keys disabled in gaming mode (Alt+Tab, Alt+F4, Win - order not established) | from driver |
| 62-63 | `aa 55` | confirmed |

Values 0-8 in byte 0 are the effects of an older "Gaming Force" keyboard family
(Breathing, Reactive, SpectrumCycling, Static, Wave, Explosion, HeartBeating,
OwnerDraw) that the same tool drives when `ToolType = 0`. That family uses a
different lighting block layout (64 byte records) which is not described here.

### 6.2 Key map (`04 11`), 0x280 bytes **[from driver]**

144 entries of 4 bytes laid out as the 8 x 18 matrix (as in 5.2), closed by
`aa 55` at offset 0x27E. `00 00 00 00` means the default key.

| Byte 0 | Type | Bytes 1-3 |
|---|---|---|
| `01` | mouse function | `01 mm 00` buttons (mask: 01 left, 02 right, 04 middle, 08, 10); `03 01 00` wheel up, `03 ff 00` wheel down |
| `02` | key | `mod usage 00`; `mod` = HID modifier mask (01 LCtrl, 02 LShift, 04 LAlt, 08 LWin, 10 RCtrl, 20 RShift, 40 RAlt, 80 RWin), `usage` = HID key code |
| `03` | media key | Consumer usage u16 LE, `00` (`e9 00` volume up, `ea 00` volume down, `e2 00` mute, `cd 00` play/pause, `b5 00` next, `b6 00` previous, `b7 00` stop, `23 02` home page, `94 01` my computer, `8a 01` mail, `92 01` calculator) |
| `04` | special (`01`, `02`, `04` in byte 1) | meaning not established |
| `05` | host side action | `02 nn tt` start program `nn`; `03 ...` not established (probably profile switch) |
| `06` | macro | `index mode repeat` |
| `07` | key combination | up to three HID key codes |

The tool's "Windows" shortcuts are plain type `02` entries: `02 03 29`
(Ctrl+Shift+Esc), `02 08 07` (Win+D), `02 04 2b` (Alt+Tab), `02 04 3d`
(Alt+F4), `02 01 1b/06/19` (Ctrl+X/C/V).

### 6.3 Macros (`04 15`) **[from driver, partial]**

- 0x190 bytes: a table of 100 x u32 - the offset of each macro inside the block
  or `FFFFFFFF`.
- Each macro: an 8 byte header (including the step count as u16 LE) followed by
  4 byte steps.
- Key step: `[2]` = key code, `[3]` = `type << 4`, bit 7 set for one of the
  directions (press / release).
- Delay step (type 5): 24 bit time in bytes 0-2 and its top nibble in byte 3.
- The block is padded to 64 bytes and followed by one more packet ending in
  `aa 55`.
- The size must not exceed the capacity from the information block.

## 7. Notifications from the keyboard **[from driver]**

The vendor collection (`FFFF/01`) sends input report id `05` with three data
bytes. The vendor tool reads it with a 2 s timeout and hands the first two
bytes to the application. It serves actions carried out on the host (key type
`05`: start a program, switch profile). The actual values have not been
captured.

## 8. Open questions

- What `04 18`, `04 19`, `04 F0` and `04 F1` do.
- Effects numbered 20-32 and the behaviour of brightness / speed 0.
- Whether commands that read the stored configuration exist (even opcodes
  `04 10`-`04 16`?).
- The meaning of bytes 0 and 10-11 of the information block.
- The order of the gaming mode flags, the full macro format and the contents
  of notifications.
