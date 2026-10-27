# Live Hardware Test Results (Persistent Connection - DTR=False)

Port: `COM3` | Baud: `115200` | Active Test Duration: 5.0s per dialect

| ID | Configuration / Dialect | Baud | Status | Sent Packet (TX) | Response (RX) |
| :---: | :--- | :---: | :---: | :--- | :--- |
| 01 | uHand UNO Standard (0xAA 0x77) | 115200 | COMPLETED | `AA 77 01 06 B4 B4 B4 B4 ` | `No response` |
| 02 | uHand UNO Alternate Pulse (0-100% scaled) | 115200 | COMPLETED | `AA 77 01 06 64 64 64 64 ` | `No response` |
| 03 | uHand UNO Additive Checksum | 115200 | COMPLETED | `AA 77 01 06 B4 B4 B4 B4 ` | `No response` |
| 04 | Lobot Multi-Servo (0x55 0x55, CMD 0x03) | 115200 | COMPLETED | `55 55 17 03 06 90 01 01 ` | `No response` |
| 05 | Lobot Single-Servo Burst (0x55 0x55) | 115200 | COMPLETED | `55 55 08 03 01 5E 01 01 ` | `No response` |
| 06 | ASCII CSV Angles Stream | 115200 | COMPLETED | `31 38 30 2C 31 38 30 2C ` | `No response` |
| 07 | ASCII Delimited '<...>' | 115200 | COMPLETED | `3C 31 38 30 2C 31 38 30 ` | `No response` |
| 08 | ASCII PSC Protocol (#1P...) | 115200 | COMPLETED | `23 31 50 32 32 30 30 54 ` | `No response` |
| 09 | ASCII Channel Tagged (S1:180) | 115200 | COMPLETED | `53 31 3A 31 38 30 0A 53 ` | `No response` |
| 10 | Buzzer + RGB Activation + Move | 115200 | COMPLETED | `AA 77 02 04 14 02 E8 03 ` | `No response` |
