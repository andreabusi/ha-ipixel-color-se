# iPixel Color SE: piano tecnico (fase 1)

| | |
|---|---|
| **Stato** | Bozza 0.1 |
| **Data** | 2026-11-08 |
| **Input** | [specifica-funzionale.md](specifica-funzionale.md) v1.1 (i riferimenti F*n*, T*n*, V*n* rimandano lì) |
| **Dominio** | `ipixel_color_se` |
| **Repository** | https://github.com/andreabusi/ha-ipixel-color-se (codeowner `@andreabusi`) |

Il documento descrive **come** realizzare la specifica: architettura, moduli, flussi, test e ordine di lavoro. È scritto in italiano, mentre i nomi di codice (moduli, classi, chiavi) sono in inglese, come saranno nel repository.

---

## Sintesi

- **Architettura a quattro strati**:
  - le **entità** sono viste sottili, senza logica;
  - un **controller** per display contiene lo stato voluto, le regole e la riconnessione;
  - un **trasporto Bluetooth** nostro passa dallo stack di HA, quindi funziona anche con i proxy;
  - un modulo **protocol** isola pypixelcolor, che usiamo solo per costruire i comandi.
- **Una sola fonte di verità**: lo stato voluto vive nel controller ed è salvato in un unico file per display (`Store` di HA). Le entità non si leggono più a vicenda, come accadeva nel riferimento.
- **Riconnessione**: si basa su `bluetooth.async_register_advertisement_callback`, verificata nel codice di HA 2026.10: riceve ogni advertisement, anche se identico al precedente.
- **Test automatici** con `pytest-homeassistant-custom-component` su HA 2026.10.0. La CI su GitHub esegue anche hassfest e la validazione HACS.
- **Sei milestone** (§12), ognuna installabile e provabile sul tuo HA. Le prove sul pannello (V1–V12) sono distribuite nelle milestone in cui servono.

---

## 1. Vincoli tecnici verificati

Valori letti dal codice sorgente di HA al tag `2026.10.0` e dal pacchetto pypixelcolor 0.5.0.

| Elemento | Valore | Conseguenza |
|---|---|---|
| Python richiesto da HA 2026.10 | 3.14 | Ambiente di sviluppo e CI su Python 3.14 |
| Bleak / bleak-retry-connector / habluetooth | 3.0.2 / 4.7.1 / 7.1.2, forniti da HA | Non vanno elencati nei `requirements` del manifest |
| pypixelcolor | 0.5.0, licenza MIT, dipende da `bleak`, `crccheck`, `pillow` senza versioni fissate | Nel manifest solo `pypixelcolor==0.5.0`: pin esatto, perché usiamo moduli interni |
| `set_clock_mode` di pypixelcolor | Accetta gli stili 0–8 | Il pannello mostra gli stili 1–9 e ignora lo 0 (V5): usiamo 1–8. Il 9 arriverà con una PR a pypixelcolor e un aggiornamento del pin. |
| Trasporto di pypixelcolor | Crea un proprio `BleakClient` dall'indirizzo | Non passa dai proxy di HA: usiamo pypixelcolor solo per costruire i comandi, il trasporto è nostro |
| `async_register_advertisement_callback` | Esiste. Riceve ogni pacchetto, una volta per ogni scanner che lo sente, prima che HA lo registri | Non fa replay all'avvio: il primo tentativo di connessione va fatto esplicitamente. Ha bisogno di un `await asyncio.sleep(0)` prima di connettersi, come nel riferimento. Gli aggiornamenti dell'RSSI vanno limitati. |
| `async_track_unavailable`, `async_address_present` | Disponibili | Calcolo della raggiungibilità (T1) |
| `async_address_reachability_diagnostics(…, BluetoothReachabilityIntent.CONNECTION)` | Disponibile, restituisce un testo esplicativo | Da includere nella diagnostica (F10.4) |
| Generazione degli entity_id | Nome inglese, preceduto dal nome del dispositivo e, se il dispositivo ha già un'area quando le entità vengono create, dall'area | Spiega `binary_sensor.taverna_pixel_led_display_connected` nel riferimento. Non impostiamo un'area suggerita, così gli id restano `<device>_<entity>` come nel §6 della specifica. |
| `media_source.PlayMedia` | Ha `url`, `mime_type` e `path` | I file locali si leggono da disco, senza passare dall'HTTP |
| `MediaPlayerState.BUFFERING` | Esiste | F8.5 |
| Icone del marchio | Il loader riconosce una cartella `brand/` nell'integrazione. Il componente `brands` serve solo `icon.png`, `logo.png`, le varianti `@2x` e le varianti `dark_`, senza controllare le dimensioni, e ricade su `icon.png` per quelle mancanti | Bastano `icon.png` (256×256) e `icon@2x.png` (512×512), con le dimensioni del repository `home-assistant/brands`. La validazione HACS `brands` cerca `brand/icon.png` nell'albero del repository (M5) |
| Libreria di test | `pytest-homeassistant-custom-component==0.13.371` usa `homeassistant==2026.10.0` | Test sulla versione minima supportata |

---

## 2. Architettura

```
 entità (switch, number, select, media_player, button, binary_sensor, sensor)
        │  chiamano metodi e ascoltano il controller
        ▼
 IPixelController ── stato voluto (DisplayState) ── Store (.storage)
        │  regole, riconnessione, ripristino, pianificazione dell'ora
        ├── image_source      risolve, scarica e valida le immagini
        ▼
 protocol             costruisce i comandi (SendPlan) con pypixelcolor
        ▼
 IPixelConnection     Bluetooth di HA + bleak-retry-connector, ACK, risposte, lock
```

| Modulo | Responsabilità | Dipende da HA? |
|---|---|---|
| `protocol.py` | Unico punto che importa pypixelcolor. Funzioni pure che restituiscono un `SendPlan`: `power(on)`, `brightness(level)`, `orientation(value)`, `clock_mode(style, format_24h, show_date, now)`, `set_time(now)`, `image(data, fit, width, height)`. Contiene anche la decodifica delle informazioni del pannello. | No |
| `connection.py` | `IPixelConnection`: connessione, disconnessione, invio di un `SendPlan` con attesa degli ACK, richiesta/risposta, notifica dei cambi di connessione | Sì (Bluetooth) |
| `state.py` | Dataclass `DisplayState` e `ClockSettings`, enum `Mode` e `ImageFit`, (de)serializzazione, valori di default | No |
| `controller.py` | `IPixelController`: possiede connessione, stato e Store. Espone le azioni chiamate dalle entità, applica le regole di stato, gestisce riconnessione, raggiungibilità, ripristino e sincronizzazione dell'ora, e avvisa le entità dei cambiamenti | Sì |
| `image_source.py` | Da un `media_id` (URL, `/local/…`, `media-source://…`) ottiene byte, formato e titolo. Applica il limite di 10 MB e la validazione del formato | Sì |
| `entity.py` | Classe base `IPixelEntity`: `has_entity_name`, `unique_id`, `device_info`, disponibilità, ascolto del controller | Sì |
| piattaforme | Una per tipo di entità, definite con `EntityDescription` | Sì |
| `config_flow.py` | Discovery, scelta manuale, nome, verifica della connessione | Sì |
| `diagnostics.py` | Download diagnostics | Sì |

**Perché un controller e non un `DataUpdateCoordinator`**: non c'è nulla da interrogare periodicamente (T4). Il coordinator di HA è pensato per il polling, mentre qui servono uno stato voluto, delle regole e una sequenza di comandi. Le entità si registrano con `controller.async_add_listener(callback)` e scrivono il proprio stato quando il controller le avvisa.

---

## 3. Stato e persistenza

Il controller tiene lo **stato voluto**: ciò che HA ha deciso che il pannello debba mostrare. È salvato con `homeassistant.helpers.storage.Store` (chiave `ipixel_color_se.<entry_id>`, versione 1, salvataggio ritardato di 1 s). Al posto di `RestoreEntity` su ogni entità c'è quindi un solo file coerente.

```python
@dataclass
class DisplayState:
    power: bool = True
    brightness: int | None = None        # None = mai impostata: non si invia
    orientation: int = 0
    mode: Mode | None = None             # None = sconosciuta: non si ripristina il contenuto
    clock: ClockSettings = ClockSettings(style=1, format_24h=True, show_date=True)  # stili 1–8 (V5)
    image_fit: ImageFit = ImageFit.FILL
    image: ImageRef | None = None        # media_id originale + titolo, non l'URL firmato
    auto_reconnect: bool = True
```

- I valori `None` evitano che alla prima installazione l'integrazione cambi luminosità o contenuto del pannello senza che l'utente l'abbia chiesto.
- Quando l'integrazione viene rimossa, `async_remove_entry` cancella il file.
- **Dati fissi** (indirizzo, nome, tipo, larghezza, altezza): stanno in `entry.data`, scritti dal config flow (F1.5), non nello Store.

---

## 4. Connessione e riconnessione

### 4.1 `IPixelConnection`

- **Connessione**: `async_ble_device_from_address(connectable=True)` seguito da `establish_connection(BleakClientWithServiceCache, …, ble_device_callback=…)`. Con `ble_device_callback`, i tentativi successivi usano il dispositivo più recente, per esempio se nel frattempo è cambiato il proxy. Dopo la connessione si attivano le notifiche **una volta sola**.
- **Un solo gestore delle notifiche** smista ogni frame verso l'operazione in corso: un evento di ACK oppure un future di risposta. Il riferimento invece fermava e riavviava le notifiche a ogni comando, il che costa più passaggi di rete attraverso i proxy.
- **Quando la connessione cade, il client caduto viene chiuso** con `disconnect()`. Visto in M2 sull'adattatore locale: bleak tiene aperta la connessione D-Bus del client caduto, BlueZ ne ripristina la sessione di notifica alla connessione successiva, e ogni frame arriva una volta in più per ogni connessione caduta. Chiudere il client elimina la sessione.
- **`async_send(plan)`**: sotto un `asyncio.Lock`, che serve le richieste in ordine di arrivo (F3.1, F8.10).
  - Per ogni finestra del plan scrive blocchi da 244 byte (`response=True`).
  - Se la policy del plan lo richiede, attende l'ACK `05 00 xx xx <status>`: `0` o `1` per la finestra, `3` per la fine. Il timeout è di 8 s.
  - È la stessa semantica del trasporto di pypixelcolor, applicata a **tutti** i comandi in modo uniforme. Confermato da V9 (§12): i comandi semplici ricevono un ACK in circa 30 ms, a volte prima che la scrittura sia confermata, quindi l'attesa si prepara prima di scrivere.
  - Eccezione: **`set_time`** non riceve un ACK ma il frame delle informazioni del pannello, perché è lo stesso comando. Per questo `protocol.set_time` è una richiesta con risposta.
- **`async_request(plan)`**: invia e restituisce il primo frame di risposta. Si usa per le informazioni del pannello.
- **Callback di stato**: `on_connected` e `on_disconnected(expected: bool)`. Il flag distingue un `Disconnect` voluto da una caduta della connessione.

### 4.2 Raggiungibilità e riconnessione nel controller

| Evento | Azione |
|---|---|
| Advertisement ricevuto (`async_register_advertisement_callback`) | Solo se connettibile: `reachable = True`, aggiorna l'RSSI (al massimo una scrittura ogni 30 s, vedi sotto). Se non è connesso, `auto_reconnect` è attivo, non è in pausa e non c'è un tentativo in corso, avvia la riconnessione in background. |
| `async_track_unavailable` | `reachable = False` |
| Disconnessione, voluta o no | `reachable = async_address_present(…)`: mentre era connesso il pannello non trasmetteva (V4), quindi il manager Bluetooth può averlo già dimenticato |
| Tentativo fallito, in background o da un comando | Pausa di 30 s (F3.3) per i soli tentativi in background: un comando si connette comunque |
| Comando dall'utente a pannello disconnesso | Connessione su richiesta (F3.4). Se fallisce, errore `not_reachable` |
| `Auto reconnect` riattivato | Se il pannello è presente, tentativo immediato (F3.5) |
| `Disconnect` | `auto_reconnect = False` (salvato), poi disconnessione voluta (F3.6) |
| Avvio dell'entry | Nessuna connessione bloccante (risolve P5): se `auto_reconnect` è attivo e il pannello è presente, primo tentativo esplicito in background |

**`Signal strength`** (F10.3):
- **Limite di scrittura**: una scrittura ogni 30 s al massimo, con il valore più forte sentito nell'intervallo. La prima regola prevista, "o se varia di almeno 3 dBm", è stata provata sul pannello e scartata: l'RSSI oscilla di 5–6 dBm da un advertisement all'altro (−67/−72), quindi scriveva circa due volte al secondo.
- **Quale scanner conta**: il callback si attiva una volta per ogni scanner che sente il pannello. Conta il più forte dell'intervallo, qualunque scanner l'abbia sentito: è il percorso che HA sceglierebbe per connettersi. Gli scanner non connettibili non contano.
- **Da connesso**: resta l'ultimo valore noto, cioè quello di subito prima della connessione. Il pannello non trasmette (V4), e con `unknown` il sensore non avrebbe un valore quasi mai, mentre serve proprio a capire se il pannello è al limite della portata.
- **All'avvio di HA** il valore iniziale viene dalla cronologia Bluetooth di HA (`async_last_service_info`): il callback non fa replay, e il pannello smette di trasmettere appena connesso.

La disponibilità delle entità di controllo è `connected or reachable` (T1): mentre è connesso conta solo la connessione, perché il manager Bluetooth prima o poi dimentica un pannello che non trasmette (V4). `Connected` e le entità di configurazione e diagnostica sono sempre disponibili: la regola si basa sulla categoria dell'entità.

### 4.3 Ripristino (F9)

A **ogni** connessione riuscita, compresa la prima dopo l'avvio di HA, il controller esegue sotto il proprio lock di operazione:

1. `set_time(now)` con l'ora di HA: senza corrente il pannello perde ora e data (V3);
2. `orientation`;
3. `brightness`, se impostata;
4. se `power` è falso, invia lo spegnimento e si ferma;
5. altrimenti rimostra il contenuto: `Clock` invia il comando orologio, che riaccende lo schermo e rimette la data; `Image` riscarica l'immagine e, se non è più raggiungibile, mostra l'orologio e porta `mode` su `Clock` (F9.4); se `mode` è `None` invia l'accensione.

L'ordine conta: `set_time`, orientamento e luminosità riaccendono lo schermo (V1, V7), quindi lo spegnimento deve arrivare dopo. Con lo schermo spento il pannello resta senza data finché non viene riacceso: la riaccensione manda `set_time` e l'orologio (§5). Con lo schermo spento l'immagine non viene inviata: la manda la riaccensione, perché il pannello non l'ha ricevuta su questa connessione (§5).

Il ripristino riapplica sempre lo stato completo, anche dopo un semplice riavvio di HA. È voluto: HA non può sapere se nel frattempo il pannello ha perso la corrente. Una GIF viene quindi ritrasmessa a ogni avvio di HA (§13).

**Immagine durante l'avvio di HA**: le sorgenti multimediali e gli URL di HA possono non funzionare finché HA non ha terminato l'avvio. In quel caso il passo 5 invia solo l'accensione, e l'immagine segue con un task in background registrato con `async_at_started`. Il task prende il lock come un comando qualsiasi. Il ripristino non aspetta l'avvio tenendo il lock, perché un'automazione che all'avvio manda un comando al pannello resterebbe bloccata.

Se il ripristino fallisce (un ACK mancante con la connessione ancora aperta), il controller lo registra con un warning e lo ripete prima del comando successivo: un comando non arriva mai a un pannello che non è stato ripristinato.

---

## 5. Flussi principali

**Comando semplice** (`Power`, `Brightness`, `Orientation`):
1. l'entità chiama il controller;
2. il controller prende il lock di operazione, connette se necessario e invia;
3. se l'invio riesce, aggiorna lo stato, salva e avvisa le entità;
4. se fallisce, solleva un errore tradotto (T2) e lo stato non cambia.

**`Power`**: lo spegnimento invia il comando di spegnimento. L'accensione rimostra il contenuto:
- con `mode == Clock` invia `set_time` e il comando orologio, così il pannello riceve l'ora, la data e le opzioni cambiate a schermo spento;
- con `mode == Image` invia solo l'accensione se il pannello ha già ricevuto quell'immagine, con quell'adattamento, sulla connessione corrente: la tiene in memoria anche a schermo spento (V11). Altrimenti, per esempio dopo un'interruzione di corrente, rilegge l'immagine e la reinvia, e l'immagine stessa riaccende lo schermo;
- altrimenti invia l'accensione.

Il controller ricorda l'immagine inviata sulla connessione corrente come coppia (`media_id`, `image_fit`). La dimentica a ogni nuova connessione, quando mostra l'orologio e quando un trasferimento comincia, perché un trasferimento interrotto può lasciare qualsiasi cosa sul pannello.

**Risveglio del contenuto**: luminosità e orientamento riaccendono lo schermo (V1) con ciò che il pannello aveva. Se lo schermo era spento, dopo il comando il controller:
- con `mode == Clock` invia anche `set_time` e il comando orologio, perché l'orologio del pannello può avere ora, data o opzioni vecchie;
- con `mode == Image` reinvia l'immagine solo se il pannello non l'ha ricevuta sulla connessione corrente, altrimenti mostrerebbe le GIF predefinite. Se l'ha ricevuta, la mostra già da sé (V11).

**Ripiego sull'orologio**: quando l'immagine va rimostrata senza che l'utente l'abbia chiesta, cioè nel ripristino, nella riaccensione con `Power` e nel risveglio da luminosità o orientamento, e la sorgente non si legge più, il controller mostra l'orologio, porta `mode` su `Clock` e scrive un warning nel log. Lo schermo si accende come richiesto (F9.4). Le azioni che chiedono proprio l'immagine (`play_media`, Play, `Mode = Image`, `Image fit`) falliscono invece con un errore visibile (F8.7). Un errore del pannello, cioè un ACK mancante o una scrittura fallita, resta comunque un errore.

**Regola dell'invio immediato (F6.3, D10)**:
- una modifica a `ClockSettings` aggiorna e salva sempre lo stato, ma invia il comando orologio solo se `mode == Clock`, `power` è vero e il pannello è connesso. Non apre una connessione: a pannello non raggiungibile l'opzione resta salvata e la applica il ripristino alla connessione successiva. Se l'invio fallisce compare l'errore, l'opzione resta salvata e il ripristino viene ripetuto prima del comando successivo;
- `Image fit` segue la stessa regola: rilegge e rimanda l'immagine solo se `mode == Image`, `power` è vero, il pannello è connesso e non ha già l'immagine con quell'adattamento;
- `Orientation` si invia sempre (F11.2).

**Trasferimenti (F8.10)**: un trasferimento tiene il lock di operazione dall'inizio alla fine. Un comando arrivato nel frattempo aspetta il lock e parte subito dopo l'ultimo ACK. Verificato sul pannello: una luminosità chiesta a metà di una GIF di 24 s è partita 3 ms dopo l'ACK finale.

**Regola dello stato di accensione (F5.3, F5.4)**: ogni invio riuscito di contenuto, di luminosità, di orientamento o di `set_time` imposta `power = True`, perché tutti riaccendono lo schermo (V1, V7).

**`Mode`**:
- `Clock`: comando orologio seguito da `set_time`;
- `Image`: riscarica e invia l'immagine (`image_source` + `protocol.image`), oppure un errore di validazione se non c'è un'immagine (F7.2).

**Image player, `play_media`**:
1. stato **buffering**;
2. risoluzione della sorgente;
3. invio;
4. `image` e `mode` vengono aggiornati, stato **playing**. In caso di errore il player torna allo stato precedente e mostra un errore.

Stop corrisponde a `Mode = Clock`. Lo stato del player si deriva dal controller: buffering mentre un'immagine viene letta, convertita o trasmessa, anche nel ripristino; playing se `mode == Image` e lo schermo è acceso; altrimenti idle. Dopo uno Stop, titolo e `media_content_id` restano quelli dell'ultima immagine, che Play rimanda.

**Sincronizzazione dell'ora (F6.5, F6.6)**:
- `async_track_time_change` alle 00:00:05 sincronizza l'ora e, se `mode == Clock`, rimanda il comando orologio con la nuova data. Il pannello fa avanzare la data da solo (V3), quindi è solo una garanzia;
- alle 03:05:00 sincronizza di nuovo, per coprire i cambi di ora legale europei;
- entrambe agiscono solo se c'è connessione: con `Auto reconnect` disattivo non riaprono la connessione;
- entrambe saltano uno schermo spento, perché `set_time` lo riaccenderebbe (V7): ora e data arrivano alla riaccensione;
- un errore finisce solo nel log, con un warning, perché nessuna azione dell'utente è in corso.

**`Sync time`** (F6.7): connette se necessario, invia `set_time` e, se `mode == Clock`, il comando orologio con la data di oggi. Porta `power` su vero, perché `set_time` riaccende lo schermo (V7).

Con un'immagine sullo schermo, `set_time` non la sostituisce con l'orologio (V12). Le sincronizzazioni pianificate e `Sync time` con `mode == Image` inviano quindi solo `set_time`.

L'ora viene sempre da `homeassistant.util.dt.now()` (F6.4).

---

## 6. Entità

Classe base `IPixelEntity`:
- `_attr_has_entity_name = True`, `translation_key = key`;
- `unique_id = f"{address}_{key}"`;
- `device_info` con `identifiers={(DOMAIN, address)}`, `connections={(CONNECTION_BLUETOOTH, address)}`, `manufacturer="iPixel"` e `model=f"LED Pixel Board {w}×{h}"`.

Tutti i testi stanno in `translations/en.json`, che è l'unico file di testi: niente `strings.json` separato, così non può divergere come nel riferimento (P9). Le icone stanno in `icons.json`.

| key | Piattaforma | Categoria | Note |
|---|---|---|---|
| `power` | switch | — | `controller.state.power` |
| `brightness` | number | — | Slider 1–100 %: lo 0 non spegne lo schermo e dà la stessa luce minima dell'1 (V6). Stato `None` → unknown |
| `mode` | select | — | Opzioni `clock` e `image` (da M4), tradotte in "Clock" / "Image". Stato `None` → unknown (F7.4) |
| `image_player` | media_player | — | PLAY_MEDIA, PLAY, STOP, BROWSE_MEDIA |
| `clock_style` | select | config | Opzioni `planet_yellow`, `planet_gradient`, `planet_blue`, `frame_gradient`, `frame_yellow`, `frame_multicolor`, `hourglass_yellow`, `hourglass_orange` per i valori 1–8, dal disegno della schermata dell'ora su un 32×32 (V5). Tradotte in "Planet, yellow" … "Hourglass, orange". Nello Store il valore resta un intero. |
| `clock_24h` | switch | config | Nome "Clock 24-hour format" |
| `clock_show_date` | switch | config | |
| `image_fit` | select | config | `fill` → crop, `fit` → fit |
| `orientation` | select | config | Opzioni `normal`, `rotated_counterclockwise`, `upside_down`, `rotated_clockwise` per i valori 0–3 (V8), tradotte in "Normal", "Rotated 90° counterclockwise", "Upside down", "Rotated 90° clockwise". Nello Store il valore resta un intero. |
| `auto_reconnect` | switch | config | |
| `sync_time` | button | config | |
| `disconnect` | button | config | |
| `connected` | binary_sensor | diagnostic | device_class `connectivity` |
| `width`, `height` | sensor | diagnostic | Unità `px`, valori da `entry.data` |
| `signal_strength` | sensor | diagnostic | device_class `signal_strength`, dBm, `state_class` measurement, disattivata di default. Da connesso mostra l'ultimo valore noto (§4.2) |

Le piattaforme dichiarano `PARALLEL_UPDATES = 0`, perché la serializzazione la fa già il controller.

---

## 7. Configurazione (config flow)

- **`async_step_bluetooth`**: imposta `unique_id = address` e interrompe il flusso se il pannello è già configurato. Passa poi a **`bluetooth_confirm`**, un form con il campo `name` (default il nome Bluetooth).
- **`async_step_user`**: elenca le voci di `async_discovered_service_info` che corrispondono al nome `LED_BLE_*` o al servizio `0000fa01-…`, escludendo quelle già configurate. L'elenco ha in più la voce "Enter address manually", che porta a **`manual`** (indirizzo e nome). Se non c'è nessun pannello, il flusso va direttamente a `manual`.
- **Verifica** (comune a tutti i percorsi): una `IPixelConnection` temporanea si connette e chiede le informazioni del pannello. Il comando è lo stesso di `set_time`, costruito con l'ora di HA. Poi si disconnette. In caso di errore il form viene rimostrato con `cannot_connect`.
- **Entry creata**:
  - titolo uguale al nome, che diventa il nome del dispositivo e quindi il prefisso degli entity_id;
  - `data = {address, device_type, width, height}`;
  - nessuna `options`: le impostazioni sono entità.
- **Manifest**:
  - matcher `bluetooth` su `local_name: LED_BLE_*` e `service_uuid: 0000fa01-…`, entrambi `connectable: true`. Il pannello di prova trasmette solo il nome e i manufacturer data, senza UUID, e il suo servizio GATT è `000000fa-…`: lo riconosce solo il primo matcher;
  - `dependencies: ["bluetooth_adapters", "media_source"]`;
  - `integration_type: device`, `iot_class: local_push`, `requirements: ["pypixelcolor==0.5.0"]`.

---

## 8. Immagini

`image_source.async_resolve(hass, media_id)` restituisce `ImageData(bytes, format, title)`. I casi possibili:

- `media-source://…`: `async_resolve_media`. Se `PlayMedia.path` è presente, il file si legge da disco: è il caso dei file di My media, che funzionano anche quando l'URL firmato è scaduto. Altrimenti si scarica `url`. Il titolo è il nome del file.
- `/local/…`: si legge direttamente da `config/www/…`, senza HTTP, così funziona anche durante l'avvio. Il percorso risolto deve restare dentro `www`: `..` e `%2e%2e` danno `image_unavailable`. Solo un percorso relativo che inizia con `/local/` è un file locale: un URL assoluto con un percorso `/local/` si scarica.
- `http(s)://…`: download con la sessione aiohttp di HA, timeout 30 s. Si interrompe prima di cominciare se il `Content-Length` supera 10 MB, altrimenti appena i byte ricevuti li superano (F8.8). I redirect si seguono.
- **Limite di 10 MB**: vale per il file sorgente, letto da disco o scaricato. Quello che arriva al pannello è molto più piccolo, perché viene ridotto alla sua risoluzione.
- **Formato**: si riconosce dai byte con Pillow, nell'executor, leggendo solo l'intestazione. Sono ammessi GIF, PNG, JPEG, WebP e BMP, qualunque sia l'estensione del nome.
- **Conversione** (`protocol.image`, nell'executor perché è lavoro pesante):
  - un'immagine statica diventa un PNG con Pillow prima di arrivare a pypixelcolor. Viene ruotata come dice l'EXIF, come serve per le foto dei telefoni, e i modi come CMYK o P diventano RGBA. La conversione di pypixelcolor ignora l'EXIF e non gestisce il CMYK;
  - una GIF passa così com'è: pypixelcolor la ricodifica fotogramma per fotogramma, con tempi e loop;
  - `protocol.image` ripete i passi di `send_image_hex` con le sue funzioni interne `_resize_image` e `_build_send_plan`, con `resize_method` preso da `image_fit` e le aree trasparenti rese nere. Fra i due passi porta a 256 colori la tavola globale delle GIF (V10): Pillow dimensiona ogni tavola sui colori del suo fotogramma, e il pannello si blocca su un fotogramma la cui tavola locale è più grande di quella globale. Le voci aggiunte sono nere e inutilizzate, e i fotogrammi non cambiano.
- **Trasferimento**: finestre da 12 KB, con un ACK dopo ogni finestra (`05 00 03 00 01` per una GIF, `05 00 02 00 …` per un PNG) e `… 03` alla fine. Dopo l'ultima finestra arriva solo il `03`. Si accettano solo gli ACK che ripetono i byte 2–3 della finestra (§13). Durate misurate il 2026-11-08 tramite l'adattatore USB: 4,6–5,1 s per finestra, quindi 22–24 s per una GIF da 59 KB, e 0,2–1,3 s per un'immagine piccola. Tramite il proxy non sono state misurate, perché quel giorno non era registrato in HA.
- **Riproduzione successiva**: nello stato si salva il `media_id` originale, mai l'URL firmato (F8.7).
- **Media browser**: `media_source.async_browse_media` con un filtro sui tipi MIME `image/gif`, `image/png`, `image/jpeg`, `image/webp`, `image/bmp` e `image/x-ms-bmp` (il nome che alcune versioni di Python danno al BMP). Le cartelle restano visibili.

---

## 9. Diagnostica (F10.4)

`async_get_config_entry_diagnostics` restituisce:
- `entry.data`;
- lo stato voluto completo;
- lo stato della connessione: connesso, raggiungibile, ultima connessione e ultima disconnessione, ultimo errore, adattatore o proxy dell'ultima connessione;
- l'RSSI di `Signal strength`, anche se il sensore è disattivato;
- l'ultimo `BluetoothServiceInfo`: RSSI, source (adattatore o proxy), connettibile;
- il testo di `async_address_reachability_diagnostics(…, CONNECTION)`.

La query string degli URL delle immagini, che può contenere token, si oscura con `image_source.redact_url`.

**Adattatore o proxy della connessione**: da connesso l'ultimo advertisement non lo dice (V4), e HA sceglie da solo il percorso fra gli scanner che sentono il pannello. HA non ha un'API pubblica per chiederlo, quindi `IPixelConnection.adapter` legge l'attributo privato `_connected_scanner` di `HaBleakClientWrapper`. Se l'attributo sparisse il dato diventerebbe `None`, senza errori, e `test_connection.py` lo segnalerebbe all'aggiornamento di HA. Il controller lo copia a ogni connessione, così resta leggibile dopo una disconnessione.

---

## 10. Errori

Tutte le azioni sollevano eccezioni tradotte, con `translation_domain = DOMAIN` (T2):

| Chiave | Tipo | Quando |
|---|---|---|
| `not_reachable` | `HomeAssistantError` | Connessione impossibile |
| `command_failed` | `HomeAssistantError` | Scrittura fallita o ACK mancante |
| `no_image` | `ServiceValidationError` | `Mode = Image` o Play senza immagine |
| `image_too_large` | `ServiceValidationError` | File oltre 10 MB |
| `image_unsupported` | `ServiceValidationError` | Formato non ammesso |
| `image_unavailable` | `HomeAssistantError` | Download o lettura falliti |

I messaggi sulle immagini nominano la sorgente senza la query string, che può contenere un token. Lo stesso vale per il testo dell'errore: quello di aiohttp ripete l'URL completo, quindi un errore HTTP diventa solo `<status> <messaggio>`, per esempio `429 Too Many Requests`.

I log usano `debug` per il traffico e `warning` per le disconnessioni inattese e i ripristini falliti. Il livello `info` non va usato per ogni comando, come invece fa il riferimento.

---

## 11. Qualità e strumenti

- **Ambiente**: `uv` con Python 3.14. Il `pyproject.toml` contiene solo strumenti di sviluppo, perché l'integrazione non è un pacchetto: `pytest-homeassistant-custom-component==0.13.371`, `pypixelcolor==0.5.0`, `ruff`. Pytest è configurato con `asyncio_mode = auto`.
- **Lint e formattazione**: `ruff check` e `ruff format`.
- **Test** (cartella `tests/`):

| File | Cosa verifica |
|---|---|
| `test_protocol.py` | Byte di ogni comando. Data dell'orologio passata come `DD/MM/YY` (pypixelcolor accetta solo l'anno a due cifre, e il giorno della settimana resta corretto perché 2000 anni sono cicli gregoriani completi). Decodifica delle informazioni del pannello. Immagini: fotogrammi e tempi delle GIF, tavola globale da 256 colori (V10), finestre, statiche come PNG, Fill e Fit, trasparenza, EXIF, CMYK, immagini rovinate. ACK filtrati per comando. |
| `test_image_source.py` | URL (titolo, errori, limite dal `Content-Length` e durante il download, query nascosta anche nel testo dell'errore), `/local/` (formati, percorsi fuori da `www`, limite), media source (file da disco, URL), formati non ammessi |
| `test_connection.py` | Con un `BleakClient` finto: blocchi da 244 byte, attesa degli ACK, timeout → errore, risposta catturata, ordine del lock, disconnessione inattesa |
| `test_controller.py` | Regole di accensione. Invio immediato condizionato a `Mode` (D10). Ordine del ripristino e ripristino fallito ripetuto prima del comando successivo. Riconnessione al primo advertisement (`sleep(0)`). Pausa dopo un tentativo fallito. `Disconnect` che spegne `Auto reconnect`. Connessione su richiesta. Disponibilità con V4. Ripiego sull'orologio. Ora di HA in Europe/Rome con sistema in UTC. Sincronizzazioni pianificate: mezzanotte, ora legale, schermo spento, nessuna riconnessione. |
| `test_state.py` | Default, (de)serializzazione completa, valori mancanti o non validi che tornano al default |
| `test_config_flow.py` | Discovery e conferma del nome, elenco filtrato, inserimento manuale, `cannot_connect`, `already_configured` |
| `test_init.py` | Avvio senza pannello presente (entry caricata, entità non disponibili), scaricamento dell'entry |
| `test_entities.py` | entity_id con il prefisso, categorie, disponibilità, chiamate alle azioni |
| `test_media_player.py` | Sorgenti URL, `/local/` e media source. Fit e Fill. Errori visibili (dimensione, formato, sorgente irraggiungibile). Sequenza buffering → playing, Stop → Clock, Play. Media browser filtrato, via WebSocket. Il ripristino dell'immagine, il ripiego sull'orologio, F8.10 e il riavvio di HA sono in `test_controller.py`. |
| `test_diagnostics.py` | Snapshot con syrupy, incluso in pytest-homeassistant-custom-component |

- **CI** (GitHub Actions): `hassfest`, validazione HACS (`hacs/action`), `ruff`, `pytest`.
- **Deploy sul tuo HA**: `scripts/deploy.sh`, ripreso dal riferimento. Fa rsync verso il container di HA e lo riavvia, con host e cartella config presi da impostazioni locali non versionate, con le opzioni `--dry-run`, `--logs` e `--no-restart`, e la cartella di destinazione `custom_components/ipixel_color_se`.
- **Verifiche su HA durante lo sviluppo**, tutte verificate il 2026-11-07:
  - deploy e riavvio del container li fa Claude in autonomia, con il tuo permesso;
  - log e registri si leggono via SSH;
  - stati delle entità, azioni e config flow passano dall'API REST, con un token salvato fuori dal repository;
  - le verifiche visive sul pannello e le interruzioni di corrente le fai tu.

### Rilascio

- **HACS scarica il tag così com'è**, senza zip allegato: sono una ventina di file piccoli, e uno zip richiederebbe un workflow in più da mantenere.
- **La versione** di `manifest.json` coincide con il tag (`0.1.0` e `v0.1.0`).
- **Installazione pulita sul tuo HA**: la config entry viene rimossa e riaggiunta, per provare il percorso di un nuovo utente. Il dispositivo resta senza area finché tutte le entità non esistono.

### Struttura del repository

```
ha-ipixel-color-se/
├── custom_components/ipixel_color_se/
│   ├── __init__.py  manifest.json  const.py  config_flow.py
│   ├── protocol.py  connection.py  state.py  controller.py  image_source.py
│   ├── entity.py  switch.py  number.py  select.py  button.py
│   ├── media_player.py  binary_sensor.py  sensor.py  diagnostics.py
│   ├── icons.json  translations/en.json  brand/
├── tests/
├── scripts/deploy.sh
├── specs/
├── .github/workflows/
├── pyproject.toml  hacs.json  README.md  LICENSE (GPL-3.0)  CLAUDE.md
```

**Cosa si riprende dal riferimento**:
- i matcher Bluetooth;
- l'uso di `establish_connection`;
- la decodifica degli ACK e il trasferimento a finestre;
- la riconnessione da advertisement (pausa e `sleep(0)`);
- il download con limite e il Media browser del player;
- le regole di accensione verificate sul pannello.

**Cosa non si riprende**: `common.py`, la lettura dello stato dalle altre entità, il rendering del testo, i font, le luci usate come selettori di colore.

---

## 12. Piano di lavoro

Ogni milestone termina con test verdi, deploy sul tuo HA e una prova reale.

**Durante lo sviluppo la vecchia integrazione va disattivata**: il pannello accetta una sola connessione (T5).

| # | Milestone | Contenuto | Prove sul pannello | Fatto quando |
|---|---|---|---|---|
| **M0** | Fondamenta | `git init`, struttura, `pyproject`, ruff, CI, manifest, `CLAUDE.md` (con le conoscenze sul pannello riprese dal riferimento), `deploy.sh`. L'integrazione vuota si carica. | — | La CI è verde e HA mostra l'integrazione fra quelle aggiungibili |
| **M1** | Connessione e configurazione | `protocol` (informazioni del pannello), `IPixelConnection`, config flow completo, dispositivo, `Connected`, `Width`, `Height`, diagnostica di base | **V9**: tutti i comandi usati ricevono un ACK? **V4**: il pannello continua l'advertising da connesso? | Il pannello viene rilevato, configurato con un nome e connesso. Gli entity_id hanno il prefisso. |
| **M2** | Controller e comandi base | `state`, `controller`, Store, `Power`, `Brightness`, `Orientation` (opzioni grezze), `Auto reconnect`, `Disconnect`, riconnessione, disponibilità, ripristino dei passi 1–4 | **V1**, **V2**, **V6**, **V8**. Si rinominano le opzioni di orientamento e si fissa il minimo della luminosità. | Stacco e riattacco la corrente: si riconnette da solo e rispegne lo schermo se era spento. `Disconnect` libera il pannello per l'app. |
| **M3** | Orologio | `Mode` (`Clock`), opzioni dell'orologio, `Sync time`, sincronizzazioni pianificate, ripristino dell'orologio | **V3**, **V5**, **V7**. Si danno i nomi agli stili. | Ora corretta con il fuso di HA. Lo stile cambia subito. Dopo un'interruzione di corrente torna l'orologio. |
| **M4** | Immagini | `image_source`, `Image player`, `Mode` `Image`, `Image fit`, ripristino dell'immagine con ripiego sull'orologio | **V10**, **V11**, **V12**, durata dei trasferimenti. Si corregge la tavola dei colori delle GIF. | GIF e JPG da Media browser, `/local/` e URL. `Fit` e `Fill` corretti. L'immagine torna dopo un'interruzione di corrente. |
| **M5** | Rifinitura e rilascio | `Signal strength`, diagnostica completa, icone, `brand/`, README, validazione HACS, tag `v0.1.0` su GitHub, installazione pulita definitiva sul tuo HA e rimozione della vecchia integrazione | — | La specifica è soddisfatta (§5 F1–F11). La vecchia integrazione è rimossa. |

**V9** è una prova nuova, emersa in questa fase: il trasporto di pypixelcolor attende un ACK anche per i comandi semplici (accensione, luminosità), mentre il riferimento lo trattava come facoltativo. Se qualche comando non risponde, quel comando non attenderà l'ACK e verrà considerato riuscito dopo la scrittura.

### Esiti delle prove

| Prova | Data | Esito |
|---|---|---|
| **V9** | 2026-11-07 | Luminosità, orientamento, accensione, spegnimento e orologio ricevono l'ACK `05 00 <id> <tipo> 01`, che ripete i byte 2–3 del comando. `set_time` riceve invece il frame delle informazioni `0c 00 01 80 <tipo> …`: il `set_time` di pypixelcolor, che attende un ACK, andrebbe sempre in timeout. Il pannello di prova è di tipo `0x81`, cioè 32×32. |
| **V4** | 2026-11-07 | Da connesso il pannello **smette** di trasmettere advertising, e riprende subito, più volte al secondo, appena la connessione si chiude. `Signal strength` si aggiorna quindi solo a pannello disconnesso. In M2 la raggiungibilità calcolata dagli advertising va ignorata mentre il pannello è connesso, perché il manager Bluetooth di HA prima o poi lo considera non disponibile. |
| **V8** | 2026-11-07 | I quattro valori ruotano il contenuto: 0 normale, 1 di 90° in senso antiorario (il lato in alto va a sinistra), 2 di 180°, 3 di 90° in senso orario. Il contenuto visibile ruota subito, senza essere ridisegnato. Le opzioni sono state rinominate di conseguenza (§6). |
| **V1** | 2026-11-07 | A schermo spento, un comando di luminosità **riaccende** lo schermo. Lo fa anche l'orientamento. Entrambi portano quindi `power` su vero (§5), e nel ripristino lo spegnimento va per ultimo (§4.3). V7 ha confermato che lo fa anche `set_time`. |
| **V2** | 2026-11-07 | La luminosità **resta** dopo un'interruzione di corrente: con `Disconnect` attivo, il pannello è ripartito con le GIF predefinite già attenuate, e il ripristino successivo non ha cambiato nulla. Il ripristino della luminosità resta utile per i cambi fatti da altre parti, per esempio dall'app. |
| **V6** | 2026-11-07 | La luminosità 0 non spegne lo schermo: lascia una luce minima, a occhio uguale a quella di 1. Il minimo di `Brightness` resta 1. |
| **V5** | 2026-11-07 | Sul 32×32 gli stili validi sono i valori 1–9. Lo 0 riceve l'ACK con status 1 ma non mostra nulla (resta il contenuto precedente), il 10 riceve status 0. Tutti alternano due schermate: la data (giorno della settimana in rosa, mese.giorno in azzurro, circa 5 s) e l'ora (circa 10 s), che cambia per stile: 1–3 un pianeta con l'ora sopra e minuti.secondi sotto, in giallo, gradiente o blu; 4–6 una cornice tratteggiata gradiente, gialla o multicolore; 7–9 HH:MM sopra e una clessidra con i secondi sotto, con sabbia gialla, arancione o bianca. pypixelcolor accetta 0–8, quindi usiamo 1–8 con default 1 e i nomi del §6. |
| **V7** | 2026-11-07 | `set_time` non provoca sfarfallii né fa comparire le GIF: fa ripartire il ciclo dalla schermata della data. A schermo spento **riaccende** lo schermo, mostrando l'orologio. Le sincronizzazioni pianificate saltano quindi uno schermo spento, e la riaccensione (anche da luminosità o orientamento) invia `set_time` e l'orologio (§5). |
| **V3** | 2026-11-07 | A mezzanotte il pannello fa avanzare da solo data e giorno della settimana. Senza corrente perde invece ora e data: riparte da circa 08:00:00, e il byte 8 del frame delle informazioni, che è il mese, torna a 0 finché un comando orologio non rimette la data. I byte 5 e 6 sono i minuti e i secondi appena impostati. Il ripristino copre tutto: `set_time` al passo 1, l'orologio al passo 5. |
| **V10** | 2026-11-08 | Una GIF di 4 fotogrammi restava ferma sul primo, con tempi di 1 s, 0,5 s o 0,2 s, mentre una di 36 fotogrammi a 80 ms girava. La differenza era nelle tavole dei colori: pypixelcolor salva il primo fotogramma con una tavola globale dimensionata sui suoi colori (64) e gli altri con tavole locali (128). Con tavole uguali (4 e 4, oppure 256 e 256) o locali più piccole (globale 256, locali 4) la GIF gira. Il pannello si blocca quindi sul primo fotogramma la cui tavola locale è **più grande** di quella globale. `protocol.image` porta sempre la tavola globale a 256 colori (§8): con questa correzione la GIF di 4 fotogrammi gira con i suoi tempi. |
| **V11** | 2026-11-08 | Con una GIF sullo schermo, spento e riacceso da comando, il pannello **tiene** la GIF: con il solo `power on` torna a girare, e anche la luminosità a schermo spento la riaccende. La GIF va avanti anche a schermo spento: è ricomparsa dal secondo fotogramma. Dopo un'interruzione di corrente il pannello mostra invece le GIF predefinite. La riaccensione reinvia quindi l'immagine solo se il pannello non l'ha ricevuta sulla connessione corrente (§5). |
| **V12** | 2026-11-08 | `set_time` con una GIF sullo schermo non mostra l'orologio: la GIF resta e non cambia nulla. Le sincronizzazioni pianificate e `Sync time` vanno bene anche con `mode == Image`. |
| **M4** | 2026-11-08 | Tramite l'adattatore USB. GIF dal Media browser: buffering → playing, con i tempi giusti dopo V10. Il Media browser mostra solo le immagini. JPG dal Media browser e da URL (Picsum, con un redirect verso un URL con `?hmac=…`): Fit con le bande nere sopra e sotto, Fill ritagliato, e ogni cambio di `Image fit` riscarica e rimanda. PNG trasparente da `/local/`: sfondo nero. Stop → orologio con `Mode = Clock`, Play e `Mode = Image` rimandano la foto. Errori visibili: file da 12,6 MB, TIFF, host inesistente. Un URL di Wikimedia ha risposto `429 Too Many Requests` alla sessione di HA, e l'errore ha mostrato che il testo di aiohttp ripeteva l'URL completo (§10). Luminosità a metà di un trasferimento: parte 3 ms dopo l'ACK finale. GIF scelta a schermo spento: `Power` torna acceso. Interruzioni di corrente: l'immagine torna, lo schermo spento resta spento e alla riaccensione l'immagine viene reinviata, una sorgente cancellata fa tornare l'orologio con `Mode = Clock`. Riavvio di HA: l'immagine di My media viene riletta dal disco dopo l'avvio. ACK e durate al §8. |
| **M5** | 2026-11-08 | `Signal strength`: l'RSSI oscilla di 5–6 dBm fra un annuncio e l'altro, e la regola iniziale (3 dBm o 30 s) scriveva circa due volte al secondo. Con il limite di una scrittura ogni 30 s (§4.2): una scrittura in 200 s a pannello disconnesso. Diagnostica scaricata dalla UI: adattatore, RSSI e stato completo, nessun token. Icona visibile nella pagina delle integrazioni e in quella del dispositivo, servita da `brand/`. Installazione da HACS come repository custom (`v0.1.0`): i 22 file sono identici al tag, la config entry ricreata ha gli stessi entity_id e il dispositivo non ha area. HA rimette il `disabled_by` di un'entità cancellata quando torna lo stesso `unique_id`: `Signal strength`, abilitato per le prove, è tornato abilitato ed è stato disabilitato a mano. Il default è verificato dai test. Regressione con GIF inviate per URL da uno strumento esterno, tramite il proxy ESPHome, tornato in linea e con un segnale migliore dell'adattatore USB. Interruzione di corrente: la GIF torna. Riavvio di HA con un URL temporaneo ormai scaduto (404): orologio con `Mode = Clock` (F9.4). Vecchia integrazione rimossa: nessuna entità né dispositivo orfano, e nessun errore nel log dopo il riavvio. `Power`, l'orologio e la GIF dal Media browser non sono stati riprovati a vista su questa installazione: il loro codice non è cambiato da M4. |

---

## 13. Rischi

| Rischio | Effetto | Mitigazione |
|---|---|---|
| Un comando semplice non riceve ACK (V9) | Errori spuri | Verificato in M1: tutti lo ricevono, tranne `set_time`, che riceve una risposta e viene trattato come richiesta. |
| pypixelcolor cambia i moduli interni | Rotture all'aggiornamento | Pin esatto e import confinati in `protocol.py`, coperti da `test_protocol.py` |
| Il pannello non trasmette advertising da connesso (V4) | `Signal strength` fermo durante la connessione | Confermato in M1. Da connesso il sensore mostra l'ultimo valore noto (§4.2). Si accetta e si documenta nel README (il sensore è disattivato di default) |
| `_connected_scanner` è un attributo privato di habluetooth | Un aggiornamento di HA può toglierlo | La diagnostica mostra `adapter: null`, senza errori. `test_connection.py` fallisce quando si aggiorna il pin di HA. |
| Ripristino a ogni avvio di HA | Una GIF viene ritrasmessa a ogni riavvio: fino a circa 25 s per una GIF da 60 KB tramite l'adattatore USB | Accettato: garantisce la coerenza (F9). Durante l'avvio l'immagine segue in background (§4.3) e nel frattempo il player è in buffering. |
| URL esterni non più raggiungibili al ripristino | L'immagine non torna | Ripiego sull'orologio (F9.4), verificato in M4 con un file cancellato |
| Siti che rifiutano la sessione di HA (Wikimedia risponde 429 al suo User-Agent) | Un URL che funziona nel browser fallisce in HA | L'errore è visibile con lo status HTTP. Si accetta: lo User-Agent è quello di HA. |
| ACK duplicati o in ritardo (visti in M2 con i client caduti non chiusi, ora risolto) | Nei trasferimenti a finestre un ACK in più potrebbe far partire la finestra successiva troppo presto | Risolto in M4: si accettano solo gli ACK che ripetono i byte 2–3 della finestra (V9) |
| GIF che il pannello non anima (V10) | La GIF resta ferma sul primo fotogramma | Risolto in M4: la tavola globale viene portata a 256 colori. Un aggiornamento di pypixelcolor va riverificato con una GIF di pochi colori. |
| Proxy ESPHome con WiFi instabile (visto in M2) | ACK lenti, scritture in timeout dopo 30 s, connessione che cade. Per le immagini: una finestra da 12 KB richiede circa 5 s tramite l'adattatore USB, e tramite il proxy può superare gli 8 s di attesa dell'ACK | L'errore compare nell'interfaccia (`command_failed`). Alla caduta della connessione segue la riconnessione con il ripristino, che riallinea il pannello allo stato di HA. Se i trasferimenti tramite il proxy vanno in timeout, si allunga l'attesa per le sole finestre. |
| Pannello e HA in competizione con l'app del telefono | Connessioni rubate | `Disconnect` spegne `Auto reconnect` (F3.6) |
