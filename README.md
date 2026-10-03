# Prime1 IRC Bot

Recreated from the original sykn3t Prime1 bot. Pure Python, no external dependencies.

## Setup

### 1. Copy files to your VPS
```bash
scp -r prime1/ ircd@irc.sykn3t.net:/home/ircd/prime1
```

### 2. Edit configuration
Open `prime1.py` and update the `CONFIG` block at the top:
```python
CONFIG = {
    "server": "irc.sykn3t.net",
    "port": 6697,
    "use_ssl": True,
    "nick": "Prime1",
    "owner": "YourNick",    # <-- change this
    ...
}
```

### 3. Register Prime1 with NickServ
Connect to your IRC server first, then:
```
/msg NickServ REGISTER Prime1 <password> <email>
```

Then add the NickServ identify command to prime1.py after the 001 handler:
```python
self.send_msg("NickServ", "IDENTIFY <password>")
```

### 4. Run manually to test
```bash
python3 prime1.py
```

### 5. Install as a systemd service
```bash
sudo cp prime1.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable prime1
sudo systemctl start prime1
```

## Features

### Commands
| Command | Description |
|---|---|
| `!8ball <question>` | Magic 8-ball answer |
| `!gay <text>` | Gay opinion |
| `!hug <nick>` | Hug someone |
| `!pizza [nick/everyone]` | Serve pizza |
| `!soda [nick/everyone]` | Toss a soda |
| `!milk [nick]` | Hand out milk |
| `!shot [nick]` | Pour a shot |
| `!die <nick>` | Bungee murder |
| `!chuck` | Random Chuck Norris fact |
| `!bofh` | Random BOFH error |
| `!confucius` | Confucius says... |
| `!dumblaws` | Random dumb law |
| `!emo` | Emo wisdom |
| `!drunkbot` | Prime1 gets drunk |
| `!rcupcake` | Random cupcake cannon |
| `!cupcake <nick>` | Cupcake someone |
| `!rpickpocket` | Pickpocket a random user |
| `!ryomama` | Yo mama joke |
| `!fatality <nick>` | Mortal Kombat finish |
| `!triggerme` | PM list of commands |
| `!tests` | List all % tests |
| `!<testname> <nick>` | Run a % test |

### % Tests
asshattest, babetest, bitchtest, cooltest, cutetest, drunktest, emotest,
failtest, faptest, flirttest, homotest, idiottest, jabbertest, lametest,
leettest, meattest, noobtest, piratetest, sexytest, stonedtest, sweettest, tardtest

### Keyword Triggers
- `prime` / `prime1` — name responses
- `stupid bot` — rude comebacks
- `stfu` / `damn bot` / `you stfu` — STFU variants
- `who's your daddy` — daddy responses
- `boring` — boredom responses
- `self destruct` — deflect
- `fuck you prime` — attitude
- `hi prime1` — greeting responses
- And more...

## Persistent Counters
Stored in `counters.json` in the bot directory. Tracks:
- Cupcakes given
- Pickpocket thefts
- Fatalities
- Yo mama insults

## Adding More Content
All joke pools are lists at the top of `prime1.py`:
- `CHUCK_NORRIS` — Chuck Norris facts
- `YOMAMA` — Yo mama jokes
- `BOFH_ERRORS` — BOFH errors
- `DUMB_LAWS` — Dumb laws
- `CONFUCIUS` — Confucius quotes
- `EMO_QUOTES` — Emo wisdom
- `PICKPOCKET_LOOT` — Pickpocket results

Just add strings to any list.
