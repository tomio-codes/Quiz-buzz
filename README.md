# Quiz Buzz

Bezdrátová přihlašovací tlačítka pro vědomostní soutěž: tři týmy, jeden moderátor, projektor.

První zmáčknuté tlačítko uzamkne kolo. Na projektoru se rozsvítí barva týmu, který má slovo. Moderátor mezerníkem kolo resetuje.

## Sestava

| Modul | Role |
| --- | --- |
| ESP32-C3 #1 | Červený tým |
| ESP32-C3 #2 | Zelený tým |
| ESP32-C3 #3 | Modrý tým |
| ESP32-C3 #4 | Přijímač u počítače moderátora (USB) |

Týmové moduly posílají impuls přes **ESP-NOW** (bez Wi-Fi routeru). Přijímač ho předá počítači po USB. Prohlížeč na projektoru ukáže barvu týmu.

## Zapojení týmového tlačítka

```
ESP32-C3          Tlačítko
GPIO4  ----------- jeden kontakt
GND    ----------- druhý kontakt
```

Napájení buzzeru: USB powerbanka nebo 5 V na USB-C. Vestavěná LED na GPIO8 blikne po stisku.

Tlačítko BOOT (GPIO9) funguje stejně. Při programování ho držte jen ve chvíli, kdy to žádá nahrávání.

Přijímač nepotřebuje tlačítko. Stejné GPIO4 na něm slouží jako fyzický reset kola.

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
| `arduino/receiver/receiver.ino` | Přijímač u počítače |

### PlatformIO

V adresáři `firmware`:

```bash
pio run -e team_red -t upload
pio run -e team_green -t upload
pio run -e team_blue -t upload
pio run -e receiver -t upload
```

Připojujte vždy jen jeden modul. Červený / zelený / modrý firmware se liší jen číslem týmu.

## Obrazovka moderátora

```powershell
cd host
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
```

Otevřete [http://127.0.0.1:8080](http://127.0.0.1:8080), prohlížeč dejte na projektor a zapněte celou obrazovku (F11).

- **Mezerník** nebo **R** — nové kolo
- Při více COM portech: `python server.py --port COM5`
- Bez hardwaru na zkoušku: `python server.py --demo` a klávesy **1 / 2 / 3**

Názvy a barvy týmů jsou v `host/teams.json`.

## Průběh kola

1. Moderátor položí otázku.
2. Tým, který zná odpověď, zmáčkne své tlačítko.
3. Projektor přebarví obrazovku na barvu prvního týmu.
4. Další stisky se ignorují, dokud moderátor kolo neresetuje.
