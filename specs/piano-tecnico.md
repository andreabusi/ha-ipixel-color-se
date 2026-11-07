# iPixel Color SE: piano tecnico (fase 1)

| | |
|---|---|
| **Stato** | Bozza 0.1 |
| **Data** | 2026-11-07 |
| **Input** | [specifica-funzionale.md](specifica-funzionale.md) v1.0 (i riferimenti F*n*, T*n*, V*n* rimandano lì) |
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
- **Sei milestone** (§12), ognuna installabile e provabile sul tuo HA. Le prove sul pannello (V1–V9) sono distribuite nelle milestone in cui servono.

---

## 1. Vincoli tecnici verificati

Valori letti dal codice sorgente di HA al tag `2026.10.0` e dal pacchetto pypixelcolor 0.5.0.

| Elemento | Valore | Conseguenza |
|---|---|---|
| Python richiesto da HA 2026.10 | 3.14 | Ambiente di sviluppo e CI su Python 3.14 |
| Bleak / bleak-retry-connector / habluetooth | 3.0.2 / 4.7.1 / 7.1.2, forniti da HA | Non vanno elencati nei `requirements` del manifest |
| pypixelcolor | 0.5.0, licenza MIT, dipende da `bleak`, `crccheck`, `pillow` senza versioni fissate | Nel manifest solo `pypixelcolor==0.5.0`: pin esatto, perché usiamo moduli interni |
| Trasporto di pypixelcolor | Crea un proprio `BleakClient` dall'indirizzo | Non passa dai proxy di HA: usiamo pypixelcolor solo per costruire i comandi, il trasporto è nostro |
| `async_register_advertisement_callback` | Esiste. Riceve ogni pacchetto, una volta per ogni scanner che lo sente, prima che HA lo registri | Non fa replay all'avvio: il primo tentativo di connessione va fatto esplicitamente. Ha bisogno di un `await asyncio.sleep(0)` prima di connettersi, come nel riferimento. Gli aggiornamenti dell'RSSI vanno limitati. |
| `async_track_unavailable`, `async_address_present` | Disponibili | Calcolo della raggiungibilità (T1) |
| `async_address_reachability_diagnostics(…, BluetoothReachabilityIntent.CONNECTION)` | Disponibile, restituisce un testo esplicativo | Da includere nella diagnostica (F10.4) |
| Generazione degli entity_id | Nome inglese, preceduto dal nome del dispositivo e, se il dispositivo ha già un'area quando le entità vengono create, dall'area | Spiega `binary_sensor.taverna_pixel_led_display_connected` nel riferimento. Non impostiamo un'area suggerita, così gli id restano `<device>_<entity>` come nel §6 della specifica. |
| `media_source.PlayMedia` | Ha `url`, `mime_type` e `path` | I file locali si leggono da disco, senza passare dall'HTTP |
| `MediaPlayerState.BUFFERING` | Esiste | F8.5 |
| Icone del marchio | Il loader riconosce una cartella `brand/` nell'integrazione | Icona e logo direttamente nel repository (M5) |
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
    clock: ClockSettings = ClockSettings(style=0, format_24h=True, show_date=True)
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
- **`async_send(plan)`**: sotto un `asyncio.Lock`, che serve le richieste in ordine di arrivo (F3.1, F8.10).
  - Per ogni finestra del plan scrive blocchi da 244 byte (`response=True`).
  - Se la policy del plan lo richiede, attende l'ACK `05 00 xx xx <status>`: `0` o `1` per la finestra, `3` per la fine. Il timeout è di 8 s.
  - È la stessa semantica del trasporto di pypixelcolor, applicata a **tutti** i comandi in modo uniforme. Va confermato che anche i comandi semplici ricevano un ACK ([V9], §12).
- **`async_request(plan)`**: invia e restituisce il primo frame di risposta. Si usa per le informazioni del pannello.
- **Callback di stato**: `on_connected` e `on_disconnected(expected: bool)`. Il flag distingue un `Disconnect` voluto da una caduta della connessione.

### 4.2 Raggiungibilità e riconnessione nel controller

| Evento | Azione |
|---|---|
| Advertisement ricevuto (`async_register_advertisement_callback`) | `reachable = True`, aggiorna l'RSSI (al massimo una scrittura ogni 30 s, oppure se varia di almeno 3 dBm). Se non è connesso, `auto_reconnect` è attivo, non è in pausa e non c'è un tentativo in corso, avvia la riconnessione in background. |
| `async_track_unavailable` | `reachable = False` |
| Tentativo fallito | Pausa di 30 s (F3.3) |
| Comando dall'utente a pannello disconnesso | Connessione su richiesta (F3.4). Se fallisce, errore `not_reachable` |
| `Auto reconnect` riattivato | Se il pannello è presente, tentativo immediato (F3.5) |
| `Disconnect` | `auto_reconnect = False` (salvato), poi disconnessione voluta (F3.6) |
| Avvio dell'entry | Nessuna connessione bloccante (risolve P5): se `auto_reconnect` è attivo e il pannello è presente, primo tentativo esplicito in background |

La disponibilità delle entità di controllo è `connected or reachable` (T1). `Connected` e le entità di configurazione sono sempre disponibili.

### 4.3 Ripristino (F9)

A **ogni** connessione riuscita, compresa la prima dopo l'avvio di HA, il controller esegue sotto il proprio lock di operazione:

1. `set_time(now)` con l'ora di HA;
2. `orientation`;
3. `brightness`, se impostata;
4. se `power` è falso, invia lo spegnimento e si ferma;
5. altrimenti rimostra il contenuto: `Clock` invia il comando orologio (che riaccende lo schermo); `Image` riscarica l'immagine e, se non è più raggiungibile, mostra l'orologio e porta `mode` su `Clock` (F9.4); se `mode` è `None` invia l'accensione.

Il ripristino riapplica sempre lo stato completo, anche dopo un semplice riavvio di HA. È voluto: HA non può sapere se nel frattempo il pannello ha perso la corrente. Dopo l'avvio di HA il passo 5 aspetta che HA abbia terminato l'avvio (`async_at_started`), perché le sorgenti multimediali siano pronte.

---

## 5. Flussi principali

**Comando semplice** (`Power`, `Brightness`, `Orientation`):
1. l'entità chiama il controller;
2. il controller prende il lock di operazione, connette se necessario e invia;
3. se l'invio riesce, aggiorna lo stato, salva e avvisa le entità;
4. se fallisce, solleva un errore tradotto (T2) e lo stato non cambia.

**Regola dell'invio immediato (F6.3, D10)**:
- una modifica a `ClockSettings` aggiorna sempre lo stato, ma invia il comando orologio solo se `mode == Clock` e `power` è vero;
- `Image fit` rimanda l'immagine solo se `mode == Image`;
- `Orientation` si invia sempre (F11.2).

**Regola dello stato di accensione (F5.3)**: ogni invio di contenuto riuscito imposta `power = True`.

**`Mode`**:
- `Clock`: comando orologio seguito da `set_time`;
- `Image`: riscarica e invia l'immagine (`image_source` + `protocol.image`), oppure un errore di validazione se non c'è un'immagine (F7.2).

**Image player, `play_media`**:
1. stato **buffering**;
2. risoluzione della sorgente;
3. invio;
4. `image` e `mode` vengono aggiornati, stato **playing**. In caso di errore il player torna allo stato precedente e mostra un errore.

Stop corrisponde a `Mode = Clock`. Lo stato del player si deriva dal controller: playing se `mode == Image` e lo schermo è acceso, buffering durante un trasferimento, altrimenti idle.

**Sincronizzazione dell'ora (F6.5, F6.6)**:
- `async_track_time_change` alle 00:00:05 sincronizza l'ora e, se l'orologio è visibile, rimanda il comando orologio con la nuova data;
- alle 03:05:00 sincronizza di nuovo, per coprire i cambi di ora legale europei;
- entrambe agiscono solo se c'è connessione: con `Auto reconnect` disattivo non riaprono la connessione.

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
| `brightness` | number | — | Slider 1–100 (minimo da confermare con V6). Stato `None` → unknown |
| `mode` | select | — | Opzioni `clock` e `image`, tradotte in "Clock" / "Image" |
| `image_player` | media_player | — | PLAY_MEDIA, PLAY, STOP, BROWSE_MEDIA |
| `clock_style` | select | config | Opzioni `style_1`…`style_9` → 0…8 |
| `clock_24h` | switch | config | Nome "Clock 24-hour format" |
| `clock_show_date` | switch | config | |
| `image_fit` | select | config | `fill` → crop, `fit` → fit |
| `orientation` | select | config | Inizialmente le opzioni sono `orientation_0`…`orientation_3`. Dopo V8 vengono rinominate (es. `normal`, `upside_down`). Nello Store il valore resta un intero. |
| `auto_reconnect` | switch | config | |
| `sync_time` | button | config | |
| `disconnect` | button | config | |
| `connected` | binary_sensor | diagnostic | device_class `connectivity` |
| `width`, `height` | sensor | diagnostic | Unità `px`, valori da `entry.data` |
| `signal_strength` | sensor | diagnostic | device_class `signal_strength`, dBm, `state_class` measurement, disattivata di default |

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
  - matcher `bluetooth` su `local_name: LED_BLE_*` e `service_uuid: 0000fa01-…`, entrambi `connectable: true`;
  - `dependencies: ["bluetooth_adapters", "media_source"]`;
  - `integration_type: device`, `iot_class: local_push`, `requirements: ["pypixelcolor==0.5.0"]`.

---

## 8. Immagini

`image_source.async_resolve(hass, media_id)` restituisce `ImageData(bytes, format, title)`. I casi possibili:

- `media-source://…`: `async_resolve_media`. Se `PlayMedia.path` è presente, il file si legge da disco; altrimenti si scarica `url`.
- `/local/…`: si legge direttamente da `config/www/…`, senza HTTP, così funziona anche durante l'avvio. Va verificato che il percorso risolto resti dentro `www`, per evitare l'accesso a file esterni.
- `http(s)://…`: download con la sessione aiohttp di HA, timeout 30 s, interrotto oltre 10 MB (F8.8).
- **Formato**: si riconosce dai byte con Pillow, nell'executor. Sono ammessi GIF, PNG, JPEG, WebP e BMP. L'estensione passata a pypixelcolor deriva dal formato riconosciuto, non dal nome del file.
- **Ridimensionamento e conversione**: `send_image_hex` di pypixelcolor, eseguito nell'executor perché è lavoro pesante, con `resize_method` preso da `image_fit`. pypixelcolor rende già nere le aree trasparenti.
- **Riproduzione successiva**: nello stato si salva il `media_id` originale, mai l'URL firmato (F8.7).
- **Media browser**: `media_source.async_browse_media` con un filtro sui tipi MIME `image/gif`, `image/png`, `image/jpeg`, `image/webp` e `image/bmp`.

---

## 9. Diagnostica (F10.4)

`async_get_config_entry_diagnostics` restituisce:
- `entry.data`;
- lo stato voluto completo;
- lo stato della connessione: connesso, raggiungibile, ultima connessione e ultima disconnessione, ultimo errore;
- l'ultimo `BluetoothServiceInfo`: RSSI, source (adattatore o proxy), connettibile;
- il testo di `async_address_reachability_diagnostics(…, CONNECTION)`.

Con `async_redact_data` si oscura la query string degli URL delle immagini, che può contenere token.

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

I log usano `debug` per il traffico e `warning` per le disconnessioni inattese e i ripristini falliti. Il livello `info` non va usato per ogni comando, come invece fa il riferimento.

---

## 11. Qualità e strumenti

- **Ambiente**: `uv` con Python 3.14. Il `pyproject.toml` contiene solo strumenti di sviluppo, perché l'integrazione non è un pacchetto: `pytest-homeassistant-custom-component==0.13.371`, `pypixelcolor==0.5.0`, `ruff`. Pytest è configurato con `asyncio_mode = auto`.
- **Lint e formattazione**: `ruff check` e `ruff format`.
- **Test** (cartella `tests/`):

| File | Cosa verifica |
|---|---|
| `test_protocol.py` | Byte di ogni comando. Data dell'orologio passata come `DD/MM/YY` (pypixelcolor accetta solo l'anno a due cifre, e il giorno della settimana resta corretto perché 2000 anni sono cicli gregoriani completi). Decodifica delle informazioni del pannello. |
| `test_connection.py` | Con un `BleakClient` finto: blocchi da 244 byte, attesa degli ACK, timeout → errore, risposta catturata, ordine del lock, disconnessione inattesa |
| `test_controller.py` | Regole di accensione. Invio immediato condizionato a `Mode` (D10). Ordine del ripristino. Pausa dopo un tentativo fallito. `Disconnect` che spegne `Auto reconnect`. Connessione su richiesta. Ripiego sull'orologio. Ora di HA in Europe/Rome con sistema in UTC. |
| `test_config_flow.py` | Discovery e conferma del nome, elenco filtrato, inserimento manuale, `cannot_connect`, `already_configured` |
| `test_init.py` | Avvio senza pannello presente (entry caricata, entità non disponibili), scaricamento dell'entry |
| `test_entities.py` | entity_id con il prefisso, categorie, disponibilità, chiamate alle azioni |
| `test_media_player.py` | Sorgenti URL, `/local/` e media source. Limite di dimensione e formati. Sequenza buffering → playing, Stop → Clock |
| `test_diagnostics.py` | Snapshot con syrupy, incluso in pytest-homeassistant-custom-component |

- **CI** (GitHub Actions): `hassfest`, validazione HACS (`hacs/action`), `ruff`, `pytest`.
- **Deploy sul tuo HA**: `scripts/deploy.sh`, ripreso dal riferimento. Fa rsync verso il container di HA e lo riavvia, con host e cartella config presi da impostazioni locali non versionate, con le opzioni `--dry-run`, `--logs` e `--no-restart`, e la cartella di destinazione `custom_components/ipixel_color_se`.
- **Verifiche su HA durante lo sviluppo**, tutte verificate il 2026-11-07:
  - deploy e riavvio del container li fa Claude in autonomia, con il tuo permesso;
  - log e registri si leggono via SSH;
  - stati delle entità, azioni e config flow passano dall'API REST, con un token salvato fuori dal repository;
  - le verifiche visive sul pannello e le interruzioni di corrente le fai tu.

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
| **M4** | Immagini | `image_source`, `Image player`, `Mode` `Image`, `Image fit`, ripristino dell'immagine con ripiego sull'orologio | — | GIF e JPG da Media browser, `/local/` e URL. `Fit` e `Fill` corretti. L'immagine torna dopo un'interruzione di corrente. |
| **M5** | Rifinitura e rilascio | `Signal strength`, diagnostica completa, icone, `brand/`, README, validazione HACS, tag `v0.1.0` su GitHub, installazione pulita definitiva sul tuo HA e rimozione della vecchia integrazione | — | La specifica è soddisfatta (§5 F1–F11). La vecchia integrazione è rimossa. |

**V9** è una prova nuova, emersa in questa fase: il trasporto di pypixelcolor attende un ACK anche per i comandi semplici (accensione, luminosità), mentre il riferimento lo trattava come facoltativo. Se qualche comando non risponde, quel comando non attenderà l'ACK e verrà considerato riuscito dopo la scrittura.

---

## 13. Rischi

| Rischio | Effetto | Mitigazione |
|---|---|---|
| Un comando semplice non riceve ACK (V9) | Errori spuri | Si verifica in M1. Per quel comando l'ACK diventa facoltativo. |
| pypixelcolor cambia i moduli interni | Rotture all'aggiornamento | Pin esatto e import confinati in `protocol.py`, coperti da `test_protocol.py` |
| Il pannello non trasmette advertising da connesso (V4) | `Signal strength` fermo durante la connessione | Si accetta e si documenta (il sensore è disattivato di default) |
| Ripristino a ogni avvio di HA | Una GIF viene ritrasmessa a ogni riavvio, qualche secondo di trasferimento | Accettato: garantisce la coerenza (F9) |
| URL esterni non più raggiungibili al ripristino | L'immagine non torna | Ripiego sull'orologio (F9.4), già deciso |
| Pannello e HA in competizione con l'app del telefono | Connessioni rubate | `Disconnect` spegne `Auto reconnect` (F3.6) |
