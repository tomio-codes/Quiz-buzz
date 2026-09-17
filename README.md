# Quiz Buzz

Bezdrátová přihlašovací tlačítka pro vědomostní soutěž: 2–4 týmy, jeden moderátor, projektor.

První zmáčknuté tlačítko uzamkne kolo. Na projektoru se rozsvítí barva týmu, který má slovo. Moderátor přidělí body, mezerníkem kolo resetuje a na konci ukáže pořadí.

## Sestava

| Modul | Role |
| --- | --- |
| ESP32-C3 | Červený tým |
| ESP32-C3 | Zelený tým |
| ESP32-C3 | Modrý tým |
| ESP32-C3 | Žlutý tým (volitelně, 4 týmy) |
| ESP32-C3 | Přijímač u počítače moderátora (USB) |

Týmové moduly komunikují přes **ESP-NOW** (bez Wi-Fi routeru). Přijímač předá události počítači po USB. Prohlížeč na projektoru zobrazuje barvu týmu, skóre a stav hry.

## Krabička týmového tlačítka

Každé tlačítko je v samostatné krabičce s vlastním napájením:

```
LiPo baterie → modul TP4056 (nabíjení) → buck/boost 3,3 V → ESP32-C3
```

- **TP4056** — nabíjení z USB (micro nebo USB-C podle modulu) a ochrana baterie.
- **Buck/boost na 3,3 V** — stabilní napájení pro ESP32-C3 z celého rozsahu vybití článku.
- Při programování lze desku napájet přímo přes USB; v provozu běží z baterie v krabičce.

## Zapojení na ESP32-C3 (týmové tlačítko)

| Pin | Funkce |
| --- | --- |
| **GPIO4** | Herní tlačítko (jeden kontakt na GND, druhý na GPIO4, `INPUT_PULLUP`) |
| **GPIO3** | Výstup pro rozsvícení tlačítka — po přihlášení do kola (LOCK) jde HIGH, po resetu LOW |
| **GPIO8** | Vestavěná LED na desce — krátce blikne po stisku |

```
GPIO4  ————  tlačítko  ————  GND
GPIO3  ————  LED / indikátor v krabičce (přes tranzistor, pokud je potřeba)
```

Hra reaguje jen na **GPIO4**. Pin GPIO9 (BOOT na desce) se pro hru nepoužívá.

## Přijímač

Přijímač je napájen z USB počítače moderátora. Nepotřebuje baterii.

- **GPIO4** nebo **GPIO9** — fyzický reset kola (stejně jako příkaz z počítače).
- **GPIO8** — LED indikace uzamčeného kola.

## Nahrání firmware

### Arduino IDE

Skici jsou v `arduino/`. Každá má vlastní složku — otevřete soubor `.ino`, ne celý projekt.

1. Nainstalujte [Arduino IDE](https://www.arduino.cc/en/software) a balíček desek **esp32** (Espressif) přes *Boards Manager*.
2. V *Tools* nastavte:
   - **Board:** ESP32C3 Dev Module
   - **USB CDC On Boot:** Enabled
   - **Flash Mode:** DIO
3. Připojte vždy jen jeden modul a vyberte jeho COM port.
4. Otevřete a nahrajte:

| Soubor | Modul |
| --- | --- |
| `arduino/team_red/team_red.ino` | Červený tým |
| `arduino/team_green/team_green.ino` | Zelený tým |
| `arduino/team_blue/team_blue.ino` | Modrý tým |
| `arduino/team_yellow/team_yellow.ino` | Žlutý tým |
| `arduino/receiver/receiver.ino` | Přijímač u počítače |

### PlatformIO

V adresáři `firmware`:

```bash
pio run -e team_red -t upload
pio run -e team_green -t upload
pio run -e team_blue -t upload
pio run -e team_yellow -t upload
pio run -e receiver -t upload
```

Připojujte vždy jen jeden modul. Firmware týmů se liší jen číslem týmu (`TEAM_ID`).

## Obrazovka moderátora

```powershell
cd host
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
```

Otevřete [http://127.0.0.1:8080](http://127.0.0.1:8080), prohlížeč dejte na projektor a zapněte celou obrazovku (F11).

### Parametry serveru

| Parametr | Význam |
| --- | --- |
| `--teams 2` | Červený + modrý tým |
| `--teams 3` | Červený + zelený + modrý (výchozí) |
| `--teams 4` | Všechny čtyři barvy včetně žlutého |
| `--port COM5` | Sériový port přijímače (bez parametru se použije jediný nalezený port) |
| `--http-port 8080` | Port webového rozhraní |
| `--demo` | Bez hardwaru — simulace stisků klávesami v prohlížeči |

Příklady:

```powershell
python server.py --teams 2
python server.py --teams 4 --port COM8
python server.py --demo --teams 3
```

Po startu server **čeká na připojení všech zvolených tlačítek** (heartbeat každou 1 s). Teprve potom hra přejde do režimu připraveno. Na obrazovce jsou barevné tečky — svítí při spojení, blikají při výpadku.

### Ovládání v prohlížeči

- **Mezerník** nebo **R** — reset kola (nové přihlášení)
- **+1 / +2 / +3** — body za správnou odpověď (po přihlášení týmu)
- **Konec** — ukončení soutěže a zobrazení pořadí
- **Nová hra** — vynulování skóre a nový začátek

V demo režimu simulujte stisky klávesami **1–4** podle čísla týmu (jen aktivní týmy dle `--teams`).

Názvy a barvy týmů jsou v `host/teams.json`.

## Průběh hry

1. Server nastartuje a čeká na připojení tlačítek (`--teams`).
2. Moderátor položí otázku.
3. Tým, který zná odpověď, zmáčkne tlačítko na **GPIO4**.
4. Projektor přebarví obrazovku na barvu prvního týmu; na modulu se rozsvítí indikátor na **GPIO3**.
5. Moderátor zvolí body (+1 / +2 / +3) nebo resetuje kolo bez bodů.
6. Další stisky se ignorují, dokud moderátor kolo neresetuje.
7. Při ztrátě spojení s tlačítkem (> 5 s bez heartbeat) se hra pozastaví do obnovení signálu.

## Struktura projektu

```
quiz-buzz/
├── arduino/          # Skici pro Arduino IDE (týmy + přijímač)
├── firmware/         # Stejný firmware pro PlatformIO
├── host/
│   ├── server.py     # Python server, sériový port, logika hry
│   ├── teams.json    # Názvy a barvy týmů
│   └── static/       # Webové rozhraní pro projektor
└── README.md
```
