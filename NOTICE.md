# Notices

## Unofficial tool

F1 Telemetry is an unofficial, independent, fan-made tool. It is not affiliated with, authorised
by, endorsed by, or connected to Formula 1, Formula One World Championship Limited, the FIA,
Electronic Arts Inc., Codemasters, or any Formula 1 team, driver or circuit.

## Trademarks

F1, FORMULA 1, FORMULA ONE, GRAND PRIX and related marks are trademarks of Formula One Licensing
BV. EA and Codemasters are trademarks of Electronic Arts Inc. Team, driver, sponsor and circuit
names belong to their respective owners. They appear here only to label the data the game sends.
No affiliation or endorsement is claimed, and no team, series or sponsor logos or artwork are
bundled with this software.

## Telemetry data

This app records the UDP telemetry stream that your own copy of the game broadcasts on your own
network. It does not connect to the publisher's servers, modify the game, or bypass any technical
protection.

Recordings can contain other players' online names and results. **You are responsible for how you
record, store and share that data** — including any consent that applies where you live, and the
game's own terms of service. Share captures only with people who expect it.

## Accuracy

Results, standings, lap times and telemetry are a best-effort reading of the game's UDP stream and
can be incomplete or wrong — packets are lost on wireless networks, and a session that ends without
a final-classification packet is reconstructed and marked as such in the app. Nothing here is an
official result.

---

## Third-party components

F1 Telemetry itself is licensed under the terms in [`LICENSE`](LICENSE). That licence covers **only
the F1 Telemetry source code**. The components below are licensed separately by their own authors,
and their licences are unaffected by it.

| Component | Licence |
|---|---|
| Python | Python Software Foundation License |
| PySide6 / Qt 6 | **GNU LGPL v3** (PySide6 is offered as LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only; used here under LGPL-3.0-only) |
| NumPy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| Apache Arrow (pyarrow) | Apache License 2.0 |
| SQLAlchemy | MIT |
| PyQtGraph | MIT |
| python-zstandard (bundling libzstd) | BSD-3-Clause (libzstd: BSD-3-Clause / GPLv2) |
| SQLite | Public domain |
| PyInstaller bootloader | GPL 2.0+ with the bootloader exception |
| flag-icons (nationality flags) | MIT |

Each component's full licence text ships inside its own distribution metadata in the `_internal`
folder beside the executable.

### Qt / PySide6 (LGPL v3)

Release builds of F1 Telemetry include **unmodified** Qt 6 and PySide6 libraries, used under the GNU
Lesser General Public License version 3. Qt is not modified in any way. The Qt libraries ship as
separate files in the `_internal` folder beside the executable and may be replaced with compatible
versions. Licensing information and sources: <https://www.qt.io/licensing/> and
<https://download.qt.io/>.

### Apache Arrow (Apache License 2.0)

Apache Arrow is distributed under the Apache License 2.0. Its required `NOTICE` file ships with the
`pyarrow` distribution metadata in the `_internal` folder.

### Nationality flags

The nationality flag SVGs are from the **flag-icons** project by Panayiotis Lipiridis
(<https://github.com/lipis/flag-icons>), set `flags/4x3`, used under the MIT License.

> Copyright (c) 2013 Panayiotis Lipiridis
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
> associated documentation files (the "Software"), to deal in the Software without restriction,
> including without limitation the rights to use, copy, modify, merge, publish, distribute,
> sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or
> substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
> NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
> NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
> DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The full notice, including the file-naming scheme and the nationality-id mapping, is in
[`src/ui/assets/flags/ATTRIBUTION.md`](src/ui/assets/flags/ATTRIBUTION.md).
