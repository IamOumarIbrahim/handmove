# uHand UNO Configuration Sweep Report

Last updated: Config 29/29 completed.

| ID | Configuration Name | Port | Baud | Status | Sent Sample (TX) | Received Feedback (RX) |
| :---: | :--- | :---: | :---: | :---: | :--- | :--- |
| 01 | uHand UNO (0xAA 0x77) Bitwise Inv Checksum | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 02 | uHand UNO (0xAA 0x77) Bitwise Inv Checksum | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 03 | uHand UNO (0xAA 0x77) Additive Checksum | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 04 | uHand UNO (0xAA 0x77) Additive Checksum | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 05 | uHand UNO Unlock RGB + Move | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 06 | uHand UNO Unlock RGB + Move | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 07 | Lobot Multi-Servo (0x55 0x55, CMD=0x03) | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (55 55 17 03 06 90 01` | `No response` |
| 08 | Lobot Multi-Servo (0x55 0x55, CMD=0x03) | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (55 55 17 03 06 90 01` | `No response` |
| 09 | Lobot Single-Servo Burst (0x55 0x55) | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (55 55 08 03 01 5E 01` | `No response` |
| 10 | Lobot Single-Servo Burst (0x55 0x55) | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (55 55 08 03 01 5E 01` | `No response` |
| 11 | LewanSoul Bus Servo Frame (ID-first) | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (55 55 01 07 01 84 03` | `No response` |
| 12 | LewanSoul Bus Servo Frame (ID-first) | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (55 55 01 07 01 84 03` | `No response` |
| 13 | ASCII CSV Angle Stream | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (31 38 30 2C 31 38 30` | `No response` |
| 14 | ASCII CSV Angle Stream | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (31 38 30 2C 31 38 30` | `No response` |
| 15 | ASCII Bracketed Angles '<...>' | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (3C 31 38 30 2C 31 38` | `No response` |
| 16 | ASCII Bracketed Angles '<...>' | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (3C 31 38 30 2C 31 38` | `No response` |
| 17 | ASCII PSC Protocol (#1P2000T500!) | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (23 31 50 32 32 30 30` | `No response` |
| 18 | ASCII PSC Protocol (#1P2000T500!) | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (23 31 50 32 32 30 30` | `No response` |
| 19 | ASCII Channel Tagged (S1:180) | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (53 31 3A 31 38 30 0A` | `No response` |
| 20 | ASCII Channel Tagged (S1:180) | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (53 31 3A 31 38 30 0A` | `No response` |
| 21 | ASCII Single Character ('O'/'C') | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (4F 0A...)` | `No response` |
| 22 | ASCII Single Character ('O'/'C') | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (4F 0A...)` | `No response` |
| 23 | uHand UNO (0xAA 0x77) @ 57600 baud | `COM3` | 57600 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 24 | Lobot Multi-Servo (0x55 0x55) @ 57600 baud | `COM3` | 57600 | ✔️ COMPLETED | `5 pkts (55 55 17 03 06 90 01` | `No response` |
| 25 | uHand UNO (0xAA 0x77) @ 38400 baud | `COM3` | 38400 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 26 | uHand UNO (0xAA 0x77) @ 19200 baud | `COM3` | 19200 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 27 | uHand UNO without DTR Reset (dtr=False) | `COM3` | 9600 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 28 | uHand UNO without DTR Reset (dtr=False) | `COM3` | 115200 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |
| 29 | COM1 Cross-Check (uHand UNO 0xAA 0x77) | `COM1` | 9600 | ✔️ COMPLETED | `5 pkts (AA 77 01 06 B4 B4 B4` | `No response` |