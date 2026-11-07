# iPixel Color per Home Assistant: specifica funzionale (fase 1)

| | |
|---|---|
| **Stato** | Versione 1.0: decisioni chiuse, pronta per il piano tecnico. Le prove sul pannello (§10) si fanno all'inizio dell'implementazione. |
| **Data** | 2026-11-07 |
| **Dominio** | `ipixel_color_se` |
| **Riferimento** | `ha-ipixel-color`, branch `import-server-version` (commit `a93b813` + modifiche non committate: riconnessione in background, stato di accensione) |
| **Libreria protocollo** | `pypixelcolor` 0.5.0 |

Questo documento definisce **cosa** deve fare la nuova integrazione, non **come**: l'architettura e il codice saranno oggetto del piano tecnico successivo. Le decisioni prese sono raccolte nel §9. Le cose da provare sul pannello sono marcate **[Vn]** (§10).

**Convenzione di lingua**: nomi delle entità, entity_id, testi dell'interfaccia e codice sono **in inglese**. Questo documento è in italiano, ma riporta i nomi delle entità in inglese, così come compariranno in HA.

---

## Sintesi

- **Cosa fa la fase 1**: accensione e luminosità dello schermo, orologio, invio di immagini (GIF animate e immagini statiche), orientamento, connessione con riconnessione automatica, diagnostica. Il testo arriverà in una fase successiva.
- **Entità**: 16 per display, con nomi in inglese e il prefisso del nome che scegli durante la configurazione, per esempio `switch.pixel_taverna_power`. L'elenco completo è nel §6.
- **Installazione pulita**: dominio `ipixel_color_se`. Prima di aggiungere il pannello alla nuova integrazione va rimosso dalla vecchia, e automazioni e dashboard vanno aggiornate a mano.
- **Invio immediato**: niente più Auto Update né Update Display. Una modifica viene inviata subito al display se il contenuto a cui si riferisce è visibile. Per esempio, lo stile dell'orologio cambiato mentre è visibile un'immagine viene applicato quando torni all'orologio.
- **`Mode` decide cosa si vede**: `Clock` o `Image`, in futuro anche `Text`. L'`Image player` porta `Mode` su `Image`, e lo Stop la riporta su `Clock`.
- **Ripristino dopo ogni riconnessione**, per esempio dopo un'interruzione di corrente: l'integrazione reinvia ora, luminosità e orientamento, rispegne lo schermo se era spento, altrimenti rimostra l'ultimo contenuto. Il pannello non resta più sulle GIF predefinite.
- **`Disconnect`** libera il pannello per l'app del telefono e spegne `Auto reconnect`. HA riprende il controllo quando riattivi `Auto reconnect` o invii un comando.
- **Limiti noti**:
  - il pannello non comunica né l'accensione né la luminosità, quindi HA mostra l'ultimo stato inviato (con il ripristino resta affidabile);
  - l'ultima immagine viene riscaricata dalla sorgente quando serve: un URL temporaneo che non esiste più non può essere rimostrato.
- **Requisiti**: Home Assistant 2026.10.0 o successivo, licenza GPL-3.0, pubblicazione su GitHub (HACS in seguito).

---

## 1. Obiettivi

1. Riscrivere l'integrazione per i display LED Bluetooth iPixel Color (venduti come "B.K. Light LED Pixel Board"), partendo da quella esistente.
2. Esporre **poche entità chiare**, tutte riconoscibili come appartenenti al proprio display.
3. Mantenere ciò che oggi funziona bene: discovery, connessione via proxy Bluetooth, riconnessione automatica, player GIF, stato di connessione.
4. Portare in fase 1 solo funzioni affidabili: accensione, luminosità, orologio, immagini (GIF animate e statiche).
5. Lasciare spazio per aggiungere la gestione del testo in una fase successiva, senza stravolgere le entità.

**Non obiettivi della fase 1:** modalità testo (`text`, `textimage`), font, colori del testo, animazioni del testo, servizio `display_text`, migrazione dall'integrazione attuale.

---

## 2. Glossario

- **Pannello / display**: il dispositivo fisico iPixel.
- **Schermo acceso/spento**: lo stato dei LED, comandato via Bluetooth. Il pannello resta alimentato e connesso anche a schermo spento.
- **Disconnessione**: perdita del collegamento Bluetooth, di solito perché il pannello ha perso l'alimentazione.
- **Advertising**: il segnale che il pannello trasmette quando è alimentato e **non** connesso. È così che HA si accorge che è tornato.
- **Contenuto**: ciò che il pannello mostra: orologio, un'immagine (GIF animata o immagine statica), oppure le GIF predefinite che il pannello mostra da solo all'accensione.

---

## 3. Analisi dell'integrazione di riferimento

### 3.1 Cosa funziona e va mantenuto

- **Discovery Bluetooth**: HA propone automaticamente i pannelli il cui nome inizia con `LED_BLE_` o che espongono il servizio `FA01`. C'è anche l'aggiunta manuale da elenco o tramite indirizzo MAC.
- **Stack Bluetooth di HA**: la connessione passa da HA, quindi funziona anche attraverso i proxy ESPHome, con nuovi tentativi automatici in fase di connessione.
- **Comandi in fila**: un solo invio alla volta, così una GIF in trasferimento non viene interrotta da altri comandi.
- **Trasferimento GIF affidabile**: invio a blocchi con conferma del pannello per ciascun blocco.
- **Riconnessione in background** (modifica recente, non committata): appena il pannello torna in advertising, HA si ricollega. Dopo un tentativo fallito attende 30 s.
- **Sensore di connessione**: si aggiorna immediatamente, senza polling.
- **Player GIF**: accetta un URL, un percorso `/local/…` o un file dal Media browser (filtrato sulle sole GIF). Il pannello ripete la GIF da solo.
- **Stato di accensione** (modifica recente): il pannello non dice se lo schermo è acceso, quindi l'integrazione lo deduce dall'ultimo comando inviato. Le regole sono già state verificate sul pannello (§5.5).

### 3.2 Problemi rilevati

| # | Problema | Evidenza nel codice | Effetto per l'utente |
|---|---|---|---|
| P1 | **Entità senza prefisso del display** | Nessuna entità usa il meccanismo di HA che lega il nome al dispositivo, e i nomi sono generici ("Auto Update", "Brightness", "Mode"). L'interruttore di accensione invece prende il nome del dispositivo. | Gli entity_id registrati con le versioni precedenti di HA sono `switch.auto_update`, `number.brightness`, `select.mode`. Con due display diventano `_2`. **Verifica**: il problema sta nel codice dell'integrazione, non in una tua vecchia configurazione. |
| P2 | **Stato sparso fra le entità** | Ogni impostazione è un'entità separata. Al momento di aggiornare il display, l'integrazione rilegge i valori dalle altre entità cercandole per ID. | È fragile: tre entità (Text Animation, Text Speed, Text Rainbow) cercano le altre con un nome costruito a mano, che non corrisponde mai agli id reali, e quindi non attivano mai l'aggiornamento automatico. |
| P3 | **"Auto Update" + "Update Display"** | Una modifica alle impostazioni arriva al display solo se l'interruttore Auto Update è acceso, altrimenti serve il pulsante. | Comportamento poco comprensibile: cambi un'opzione e non succede nulla. |
| P4 | **Errori invisibili** | I comandi falliti finiscono solo nel log, e tutte le entità risultano sempre disponibili. | Premi un pulsante, non succede niente e non ricevi alcun messaggio. |
| P5 | **Avvio legato al display** | Il caricamento dell'integrazione richiede una connessione riuscita e la lettura della risoluzione dal pannello. | Se all'avvio di HA il pannello è spento, l'integrazione resta in errore e riprova con tempi crescenti. |
| P6 | **Sensori diagnostici poco utili** | "MCU Version" e "WiFi Version" valgono sempre `unknown`, perché pypixelcolor 0.5.0 non decodifica le versioni. Larghezza, altezza e tipo sono dati fissi, ma vengono interrogati ogni 30 s, e risultano "non disponibili" a pannello disconnesso. | Sensori sempre "unknown" o "non disponibile", che fanno solo rumore. |
| P7 | **Ora del pannello** | L'ora viene presa dal sistema del container, non dal fuso orario configurato in HA. Viene inviata solo all'attivazione dell'orologio o con il pulsante. | Ora sbagliata se il container ha un fuso diverso, e l'ora si sfasa dopo un riavvio del pannello. |
| P8 | **Luminosità non riapplicata** | La luminosità viene ripristinata nell'entità, ma non reinviata al pannello dopo una riconnessione. | Ciò che vedi in HA potrebbe non corrispondere al pannello (vedi [V2]). |
| P9 | **Residui** | `services.yaml` dichiara `display_text`, che però non è implementato. I due file dei testi dell'interfaccia divergono. Modello "LED Matrix Display" e versione "1.0" sono fissi nel codice. Gli stili dell'orologio si chiamano "0"–"8". | Interfaccia poco curata. |
| P10 | **Elenco di configurazione rumoroso** | L'aggiunta manuale elenca *tutti* i dispositivi Bluetooth vicini, con una stellina su quelli compatibili. | Elenco lungo e confuso. |

### 3.3 Inventario delle entità attuali e loro destino

Oggi le entità sono 27. Quelle previste sono 16 (§6).

| Entità attuale | Tipo | Destino in fase 1 |
|---|---|---|
| Power (porta il nome del dispositivo) | switch | **Mantenuta** come `Power` (§5.5) |
| Brightness | number | **Mantenuta** (§5.5) |
| Mode (textimage / text / clock) | select | **Rivista**: opzioni `Clock` / `Image`, con `Text` prevista in futuro (§5.7) |
| Clock Style | select | **Mantenuta**, con nomi degli stili leggibili |
| Clock 24h, Clock Show Date | switch | **Mantenute** |
| Sync Time | button | **Mantenuta**, più sincronizzazione automatica |
| GIF Player | media_player | **Estesa**: diventa `Image player`, per GIF e immagini statiche (§5.8) |
| Display Connected | binary_sensor | **Mantenuta** come `Connected` |
| Display Width, Display Height | sensor | **Mantenute** come `Width` e `Height` |
| Device Type | sensor | **Spostata** nelle informazioni del dispositivo (modello) |
| MCU Version, WiFi Version | sensor | **Eliminate**: sempre `unknown` |
| Auto Update | switch | **Eliminata**: ogni modifica viene inviata subito (§5.6) |
| Update Display | button | **Eliminata** |
| Display (testo) | text | Fase futura |
| Font, Text Size | select | Fase futura |
| Font Size, Line Spacing, Text Animation, Text Speed, Text Rainbow | number | Fase futura |
| Antialiasing | switch | Fase futura |
| Text Color, Background Color (luci usate come selettori di colore) | light | Fase futura, con un modello diverso |
| *(nuova)* Auto reconnect | switch | **Nuova** (§5.3) |
| *(nuova)* Disconnect | button | **Nuova** (§5.3) |
| *(nuova)* Image fit | select | **Nuova** (§5.8) |
| *(nuova)* Orientation | select | **Nuova** (§5.11) |
| *(nuova)* Signal strength | sensor | **Nuova** (§5.10) |

---

## 4. Perimetro della fase 1

**Incluso**
- Configurazione e discovery dei display
- Connessione persistente, riconnessione automatica disattivabile, disconnessione manuale
- Accensione/spegnimento dello schermo e luminosità
- Modalità orologio, con le sue opzioni e la sincronizzazione dell'ora
- Player di immagini: GIF animate e immagini statiche, con scelta dell'adattamento
- Orientamento del display
- Ripristino dello stato dopo una riconnessione
- Diagnostica: connessione, larghezza, altezza, segnale, download della diagnostica

**Escluso** (vedi anche §11)
- Tutta la gestione del testo
- Funzioni del pannello che pypixelcolor offre ma che oggi non sono esposte: programmazione oraria interna, slot salvati, timer, punteggi, modalità ritmo e fun.
- Migrazione dall'integrazione attuale: si farà un'installazione pulita (§8)

---

## 5. Requisiti funzionali

### 5.1 F1: Configurazione e discovery

- **F1.1** Quando HA rileva un pannello iPixel (nome `LED_BLE_*` o servizio `FA01`), lo propone con la notifica standard "New device discovered".
- **F1.2** L'aggiunta manuale elenca **solo** i pannelli iPixel visibili e non ancora configurati. Resta possibile inserire l'indirizzo MAC a mano.
- **F1.3** Prima di completare la configurazione l'integrazione si connette al pannello e ne legge tipo e risoluzione. Se non ci riesce, mostra un errore chiaro e permette di riprovare.
- **F1.4** L'utente dà un nome al display durante la configurazione, per esempio "Pixel Taverna". Il nome proposto è quello Bluetooth. Questo nome diventa il prefisso di tutte le entità (§5.2).
- **F1.5** Indirizzo, nome, tipo e risoluzione vengono salvati nella configurazione, così l'integrazione può avviarsi anche se il pannello è spento (risolve P5).
- **F1.6** Ogni pannello corrisponde a un dispositivo in HA. Più pannelli funzionano in modo indipendente, e lo stesso pannello non può essere aggiunto due volte.
- **F1.7** Quando l'integrazione viene rimossa o disattivata, chiude la connessione: il pannello torna libero per l'app del telefono.

*Accettazione*: un pannello acceso vicino a HA compare fra i dispositivi rilevati senza intervento. Un riavvio di HA a pannello spento non produce errori di caricamento.

### 5.2 F2: Identità del dispositivo e nomi delle entità

- **F2.1** I nomi delle entità seguono il meccanismo standard di HA. Ogni entità dichiara **solo il proprio nome** (`Power`, `Brightness`, `Clock style`…), senza prefissi scritti nel codice. HA lo combina con il nome del dispositivo:
  - il nome visualizzato diventa "Pixel Taverna Power";
  - l'entity_id diventa `switch.pixel_taverna_power`.

  Risolve P1.
- **F2.2** Ogni entità ha un nome proprio: nessuna prende il solo nome del dispositivo, così l'entity_id dice sempre di cosa si tratta.
- **F2.3** Se il dispositivo viene rinominato in HA, i nomi visualizzati delle entità lo seguono, e HA propone di aggiornare anche gli entity_id.
- **F2.4** I nomi delle entità e i testi dell'interfaccia (configurazione, errori) sono in **inglese**.
- **F2.5** Le entità sono divise nelle sezioni standard di HA: **Controls** (uso quotidiano), **Configuration** (impostazioni), **Diagnostic**.
- **F2.6** Il dispositivo riporta produttore, modello con risoluzione (per esempio "LED Pixel Board 64×16") e indirizzo Bluetooth, così HA lo collega all'adattatore o al proxy che lo vede.

*Accettazione*: con due display configurati, nessun entity_id è privo di prefisso e nessuno termina in `_2`.

### 5.3 F3: Connessione, riconnessione automatica e disconnessione

- **F3.1** Finché il pannello è raggiungibile, l'integrazione mantiene una connessione permanente. I comandi vengono eseguiti uno alla volta, nell'ordine di arrivo.
- **F3.2** L'interruttore **`Auto reconnect`** (Configuration, attivo di default) decide se l'integrazione si ricollega da sola. Il suo stato sopravvive ai riavvii di HA.
- **F3.3** **Attivo**: quando il pannello torna in advertising (tipicamente dopo essere stato ricollegato alla corrente), l'integrazione si riconnette entro pochi secondi. Dopo un tentativo fallito attende 30 s prima di riprovare.
- **F3.4** **Disattivo**: dopo una disconnessione l'integrazione non si ricollega da sola. Qualsiasi comando inviato al display (accensione, luminosità, modalità, immagine…) riapre la connessione.
- **F3.5** Se l'interruttore viene riattivato mentre il pannello è disconnesso ma visibile, la connessione parte subito.
- **F3.6** Il pulsante **`Disconnect`** (Configuration) chiude la connessione e **disattiva `Auto reconnect`**, così il pannello resta libero per l'app del telefono. Si torna alla gestione da HA in due modi: riattivando `Auto reconnect`, oppure inviando un comando.
- **F3.7** Se HA si avvia mentre il pannello è assente, le entità di controllo risultano non disponibili e la connessione parte appena il pannello compare (se `Auto reconnect` è attivo).
- **F3.8** I proxy Bluetooth ESPHome restano supportati.

*Accettazione*:
- Stacco e riattacco la corrente del pannello: entro circa 10 s dal riavvio del pannello, `Connected` torna attivo senza toccare nulla in HA.
- Premo `Disconnect`: l'app del telefono riesce a collegarsi al pannello e HA non le "ruba" la connessione.

### 5.4 F4: Stato della connessione

- **F4.1** Il sensore binario **`Connected`** (tipo connettività, Diagnostic) è attivo mentre HA è collegato al pannello e cambia stato appena la connessione cade o si ristabilisce.
- **F4.2** Il sensore è sempre disponibile, perché il suo compito è proprio indicare se il pannello è raggiungibile.

### 5.5 F5: Accensione dello schermo e luminosità

Si mantengono due entità separate, entrambe in Controls:

- **F5.1** **`Power`** (interruttore) accende e spegne lo schermo.
- **F5.2** **`Brightness`** (slider 1–100 %) regola la luminosità. Il valore viene applicato subito. [V6]
- **F5.3** Il pannello non comunica il proprio stato, quindi l'integrazione mostra l'**ultimo stato noto**, aggiornato con queste regole (già verificate sul pannello):
  - comando di accensione o spegnimento → stato corrispondente;
  - invio di qualsiasi contenuto (orologio, immagine) → acceso, perché il contenuto riaccende lo schermo;
  - riconnessione → lo stato voluto viene ripristinato (§5.9);
  - riavvio di HA → si riparte dallo stato salvato, perché il pannello non cambia.
- **F5.4** Se a schermo spento un cambio di luminosità riaccende lo schermo, `Power` deve rifletterlo. [V1]
- **F5.5** Dopo ogni riconnessione la luminosità viene reinviata al pannello (§5.9).

*Accettazione*: spengo lo schermo da HA, avvio una GIF dal player e `Power` torna acceso senza altre azioni.

### 5.6 F6: Orologio

- **F6.1** L'utente mostra l'orologio scegliendo `Clock` in `Mode` (§5.7).
- **F6.2** Le opzioni dell'orologio stanno in Configuration:
  - **`Clock style`**: 9 stili, con nomi leggibili ("Style 1" … "Style 9", oppure nomi descrittivi dopo [V5]);
  - **`Clock 24-hour format`**: acceso o spento;
  - **`Clock show date`**: acceso o spento.
- **F6.3** **Regola generale: ogni modifica viene inviata subito al display**. Non esistono più "Auto Update" né "Update Display" (risolve P3). Se l'orologio è visibile, una modifica alle sue opzioni lo aggiorna immediatamente. Se è visibile un'immagine, la modifica viene memorizzata e applicata alla prossima attivazione dell'orologio. Cambiare un'impostazione non cambia mai il contenuto mostrato: lo decide solo `Mode`.
- **F6.4** L'ora inviata al pannello è quella del **fuso orario configurato in HA** (risolve P7).
- **F6.5** L'ora viene sincronizzata automaticamente a ogni connessione, a ogni attivazione dell'orologio, almeno una volta al giorno e subito dopo i cambi di ora legale. [V7]
- **F6.6** A mezzanotte, se l'orologio è visibile, l'integrazione aggiorna la data sul pannello. È innocuo anche se il pannello la facesse avanzare da solo. [V3]
- **F6.7** Il pulsante **`Sync time`** (Configuration) resta disponibile per forzare la sincronizzazione.

*Accettazione*: con HA impostato su Europe/Rome e il container in UTC, il pannello mostra l'ora italiana. Cambiando lo stile con l'orologio visibile, il pannello si aggiorna entro un paio di secondi.

### 5.7 F7: Modalità (contenuto mostrato)

- **F7.1** Il selettore **`Mode`** (Controls) indica cosa sta mostrando il pannello, secondo l'ultimo contenuto inviato da HA. Le opzioni sono **`Clock`** e **`Image`**.
- **F7.2** Scegliere `Clock` mostra l'orologio con le opzioni correnti. Scegliere `Image` rimanda l'ultima immagine riprodotta, animata o statica. Se non c'è ancora nessuna immagine, compare un errore che invita a usare il player.
- **F7.3** Riprodurre un'immagine dal player porta `Mode` su `Image`. Lo Stop del player la riporta su `Clock`.
- **F7.4** Se HA non sa cosa mostra il pannello, `Mode` risulta "unknown".
- **F7.5** **Predisposizione al testo**: in fase 2 il selettore riceverà l'opzione `Text`. La regola di F6.3 vale anche per il testo: le sue impostazioni si applicano subito quando il testo è visibile. Le entità della fase 1 non cambiano.

### 5.8 F8: Player di immagini

- **F8.1** L'**`Image player`** (Controls) accetta come sorgente:
  - un URL http(s);
  - un percorso `/local/…`;
  - un file scelto dal **Media browser** di HA.

  È utilizzabile anche dalle automazioni con l'azione standard `media_player.play_media`.
- **F8.2** **Formati**: GIF (animata o no), PNG, JPG, WebP, BMP. Sono quelli gestiti da pypixelcolor 0.5.0. Il Media browser mostra solo i file di questi formati.
- **F8.3** **GIF animate**: conservano i tempi dei fotogrammi e il pannello le ripete in loop da solo. **Immagini statiche**: restano fisse sul pannello. Le aree trasparenti diventano nere.
- **F8.4** Il selettore **`Image fit`** (Configuration) decide come l'immagine viene adattata alla risoluzione del pannello:
  - **`Fill`** (default, il comportamento di oggi): riempie lo schermo e ritaglia l'eccesso, mantenendo le proporzioni;
  - **`Fit`**: mostra l'immagine intera, con bande nere ai lati.

  Seguendo la regola di F6.3, se un'immagine è visibile il cambio la rimanda subito con il nuovo adattamento. Altrimenti vale dalla prossima immagine.
- **F8.5** Gli stati del player:
  - **buffering** durante il trasferimento;
  - **playing** mentre l'immagine è sul pannello;
  - **idle** quando un altro contenuto l'ha sostituita.

  Il titolo mostrato è il nome del file.
- **F8.6** *Play* rimanda l'ultima immagine. *Stop* torna all'orologio (§5.7).
- **F8.7** **Nessuna copia dell'immagine**: l'integrazione ricorda solo la *sorgente* dell'ultima immagine, e la riscarica quando deve rimandarla (Play, `Mode` = `Image`, cambio di `Image fit`, ripristino dopo una riconnessione).
  - I file del Media browser funzionano sempre, perché l'integrazione ne ricorda il riferimento e non l'URL firmato, che scade.
  - Se la sorgente non è più raggiungibile (URL temporaneo, file cancellato), un'azione dell'utente fallisce con un errore visibile. Il ripristino dopo una riconnessione mostra invece l'orologio (F9.4).
- **F8.8** Un file più grande di 10 MB, un formato non supportato, un URL irraggiungibile o un trasferimento fallito producono un **errore visibile** nell'interfaccia (risolve P4).
- **F8.9** Ultima immagine e stato del player sopravvivono ai riavvii di HA.
- **F8.10** Un trasferimento in corso non viene interrotto. I comandi arrivati nel frattempo (per esempio la luminosità) vengono eseguiti subito dopo.

*Accettazione*:
- Scelgo una GIF dal Media browser: il player passa per buffering e poi playing, e la GIF gira sul pannello.
- Mando un JPG da un URL con `Image fit` = `Fit`: il pannello mostra la foto intera con bande nere. Passo a `Fill` e l'immagine viene rimandata ritagliata.

### 5.9 F9: Ripristino dopo una riconnessione

Dopo **ogni** riconnessione l'integrazione riporta il pannello allo stato voluto da HA, invece di lasciarlo sulle GIF predefinite che mostra al riavvio:

- **F9.1** sincronizza l'ora;
- **F9.2** reinvia luminosità e orientamento;
- **F9.3** se lo schermo doveva essere spento, lo rispegne, così lo stato mostrato da `Power` coincide sempre con quello reale;
- **F9.4** se lo schermo doveva essere acceso, rimostra l'ultimo contenuto:
  - l'orologio;
  - oppure l'ultima immagine, riscaricata dalla sorgente. Se la sorgente non è più raggiungibile, mostra l'orologio e porta `Mode` su `Clock`.

*Accettazione*: con l'orologio attivo stacco la corrente al pannello e la riattacco. Il pannello torna a mostrare l'orologio, non le GIF predefinite. Se lo schermo era spento, resta spento.

### 5.10 F10: Diagnostica

Tutte le entità seguenti stanno in Diagnostic:

- **F10.1** **`Connected`** (§5.4).
- **F10.2** **`Width`** e **`Height`**: numeri in pixel, letti una sola volta durante la configurazione. Restano disponibili anche a pannello disconnesso. La risoluzione compare anche nel modello del dispositivo (F2.6).
- **F10.3** **`Signal strength`**: RSSI in dBm, disattivato di default. Serve a capire se il pannello è al limite della portata del proxy. [V4]
- **F10.4** **Download diagnostics**: è la voce standard di HA nel menu della pagina del dispositivo e dell'integrazione. Scarica un file JSON con:
  - tipo, risoluzione e indirizzo del pannello;
  - stato della connessione: connesso o no, ultima disconnessione, adattatore o proxy usato;
  - `Auto reconnect`;
  - stato noto di accensione, luminosità e `Mode`;
  - opzioni dell'orologio;
  - `Image fit` e `Orientation`;
  - sorgente e nome dell'ultima immagine.

  Serve ad allegare un quadro completo alle segnalazioni su GitHub, senza dover chiedere i log.

### 5.11 F11: Orientamento

- **F11.1** Il selettore **`Orientation`** (Configuration) imposta l'orientamento del display, per esempio se il pannello è montato capovolto. Il pannello prevede 4 valori. I nomi delle opzioni si definiscono dopo la prova [V8], per esempio `Normal` e `Upside down`. Il default è quello normale.
- **F11.2** È un'impostazione del display, non di un contenuto: viene applicata subito, qualunque cosa sia visibile.
- **F11.3** Viene reinviata dopo ogni riconnessione (F9.2) e sopravvive ai riavvii di HA.

*Accettazione*: scelgo l'orientamento capovolto e il contenuto visibile si capovolge. Dopo un'interruzione di corrente resta capovolto.

---

## 6. Modello delle entità

Esempio per un display chiamato "Pixel Taverna". Nomi ed entity_id sono quelli attesi, da confermare in implementazione.

| Nome (dichiarato dall'entità) | Tipo | Sezione | entity_id atteso |
|---|---|---|---|
| Power | switch | Controls | `switch.pixel_taverna_power` |
| Brightness | number | Controls | `number.pixel_taverna_brightness` |
| Mode | select | Controls | `select.pixel_taverna_mode` |
| Image player | media_player | Controls | `media_player.pixel_taverna_image_player` |
| Clock style | select | Configuration | `select.pixel_taverna_clock_style` |
| Clock 24-hour format | switch | Configuration | `switch.pixel_taverna_clock_24_hour_format` |
| Clock show date | switch | Configuration | `switch.pixel_taverna_clock_show_date` |
| Image fit | select | Configuration | `select.pixel_taverna_image_fit` |
| Orientation | select | Configuration | `select.pixel_taverna_orientation` |
| Auto reconnect | switch | Configuration | `switch.pixel_taverna_auto_reconnect` |
| Sync time | button | Configuration | `button.pixel_taverna_sync_time` |
| Disconnect | button | Configuration | `button.pixel_taverna_disconnect` |
| Connected | binary_sensor | Diagnostic | `binary_sensor.pixel_taverna_connected` |
| Width | sensor | Diagnostic | `sensor.pixel_taverna_width` |
| Height | sensor | Diagnostic | `sensor.pixel_taverna_height` |
| Signal strength | sensor | Diagnostic (disattivato) | `sensor.pixel_taverna_signal_strength` |

---

## 7. Requisiti trasversali

- **T1 Disponibilità**: le entità di controllo sono disponibili quando il pannello è raggiungibile, cioè connesso oppure visibile via Bluetooth. Così, anche con `Auto reconnect` disattivo, un comando può riaprire la connessione. Diventano non disponibili quando il pannello è scollegato, o quando è collegato all'app del telefono e quindi non trasmette advertising. Le entità di configurazione restano sempre disponibili, perché sono impostazioni salvate in HA.
- **T2 Errori visibili**: ogni azione fallita (pannello irraggiungibile, trasferimento non riuscito, parametro non valido) mostra un messaggio nell'interfaccia e fa fallire l'automazione che l'ha lanciata, invece di finire solo nel log.
- **T3 Persistenza**: tutte le impostazioni sopravvivono ai riavvii di HA: opzioni dell'orologio, `Image fit`, `Orientation`, luminosità, accensione, modalità, sorgente dell'ultima immagine, `Auto reconnect`.
- **T4 Nessun polling**: gli stati si aggiornano a evento. I dati fissi (risoluzione, tipo) si leggono una sola volta.
- **T5 Un solo collegamento**: il pannello accetta una sola connessione Bluetooth alla volta. Mentre HA è collegato, l'app del telefono non può connettersi. Per lasciarle spazio c'è `Disconnect` (F3.6).
- **T6 Lingua**: inglese per nomi delle entità, testi dell'interfaccia, log e codice.
- **T7 Compatibilità**: Home Assistant **2026.10.0** o successivo, senza codice di compatibilità per le versioni precedenti. Il progetto viene pubblicato su GitHub e deve rispettare i requisiti per un'eventuale aggiunta a HACS.
- **T8 Verificabilità**: la logica che non richiede il pannello (regole di stato, ripristino, sincronizzazione dell'ora) deve poter essere verificata con test automatici. Il dettaglio va nel piano tecnico.
- **T9 Azioni**: in fase 1 bastano le azioni standard delle entità (`switch.turn_on`, `number.set_value`, `select.select_option`, `media_player.play_media`…), senza azioni personalizzate dell'integrazione.

---

## 8. Installazione e rapporto con l'integrazione attuale

- **Nessuna migrazione**. Si rimuove la vecchia integrazione e si aggiunge la nuova da zero. Rimuovendo la vecchia, HA cancella anche le sue entità, quindi i nuovi entity_id nascono puliti.
- Automazioni e dashboard che usano le vecchie entità vanno aggiornate a mano.
- Il dominio è `ipixel_color_se`, diverso da quello attuale (`ipixel_color`), quindi le due integrazioni possono essere installate insieme. Entrambe però propongono lo stesso pannello nella discovery. Prima di aggiungere il pannello alla nuova va rimosso dalla vecchia, perché il pannello accetta una sola connessione (T5).
- **Licenza**: GPL-3.0, come l'integrazione di riferimento da cui riprendiamo il codice, citandone l'origine nel README. pypixelcolor è MIT, quindi compatibile.

---

## 9. Decisioni

### 9.1 Prese

| ID | Decisione |
|---|---|
| D1 | Nessuna migrazione: installazione pulita (§8) |
| D1-bis | Dominio `ipixel_color_se`. Pubblicazione su GitHub, HACS da valutare in seguito (T7) |
| D2 | Due entità separate: `Power` (switch) e `Brightness` (number) (§5.5) |
| D3 | Con `Auto reconnect` disattivo, un comando riapre la connessione. `Disconnect` chiude la connessione e spegne `Auto reconnect` (§5.3) |
| D4 | Dopo ogni riconnessione si ripristina lo stato voluto (§5.9) |
| D5 | Selettore `Mode`, predisposto per `Text` (§5.7) |
| D6 | Sì a `Signal strength` e a "Download diagnostics" (§5.10) |
| D7 | Il player supporta anche immagini statiche, con il selettore `Image fit` (§5.8). Si aggiunge l'orientamento (§5.11) |
| D8 | Il nome del display viene chiesto durante la configurazione (F1.4) |
| D9 | Home Assistant 2026.10.0 o successivo (T7) |
| D10 | Una modifica a un'opzione si applica solo se il suo contenuto è visibile: è `Mode` a decidere cosa si vede (F6.3) |
| D11 | Il player si chiama `Image player` e l'opzione di `Mode` si chiama `Image` |
| D12 | Nessuna copia dell'immagine: si riscarica dalla sorgente (F8.7) |
| D13 | Nessuna azione personalizzata in fase 1 (T9) |
| D14 | Licenza GPL-3.0 (§8) |
| — | Nomi, interfaccia e codice in inglese |
| — | Diagnostica con `Width` e `Height` separati, numerici in pixel (§5.10) |
| — | Ogni modifica viene inviata subito al display: niente "Auto Update" né "Update Display" (§5.6) |

### 9.2 Aperte

Nessuna.

---

## 10. Verifiche da fare sul pannello

Nessuna di queste prove cambia le funzionalità decise: servono solo a rifinire dettagli come i nomi delle opzioni, i limiti dello slider e la frequenza della sincronizzazione. Si fanno all'inizio dell'implementazione, come primo passo.

| ID | Domanda | Perché serve |
|---|---|---|
| V1 | A schermo spento, un comando di luminosità riaccende lo schermo? | F5.4 |
| V2 | La luminosità resta impostata dopo che il pannello ha perso l'alimentazione? | Conferma l'utilità di F9.2 |
| V3 | In modalità orologio, la data avanza da sola a mezzanotte? L'ora si conserva dopo un riavvio del pannello? | Solo conferma: F6.5 e F6.6 coprono già entrambi i casi |
| V4 | Il pannello continua l'advertising mentre è connesso? | Se smette, `Signal strength` si aggiorna solo da disconnesso (F10.3) |
| V5 | Come appaiono i 9 stili dell'orologio? | Dare nomi descrittivi (F6.2) |
| V6 | Cosa fa la luminosità 0? pypixelcolor la accetta, il riferimento parte da 1 | Limite inferiore di `Brightness` |
| V7 | La sincronizzazione dell'ora provoca sfarfallii o ridisegna il contenuto? | Frequenza della sincronizzazione (F6.5) |
| V8 | Cosa fanno i 4 valori di orientamento? Cambiarlo ridisegna subito il contenuto visibile? | Nomi delle opzioni di `Orientation` (F11.1) |
| V9 | Anche i comandi semplici (accensione, luminosità, orientamento, ora) ricevono una conferma dal pannello? | Affidabilità degli errori visibili (T2), vedi il piano tecnico |

---

## 11. Evoluzioni future (fuori dalla fase 1)

- **Fase 2: testo.** Da riprogettare da zero: il modello attuale (due modalità, 12 entità di impostazione, colori tramite luci) è risultato troppo complesso. Probabilmente basterà un'azione "show text" con pochi parametri, più l'opzione `Text` in `Mode`.
- Funzioni del pannello disponibili in pypixelcolor: slot salvati sul pannello, programmazione oraria interna, timer, punteggi, modalità ritmo e fun.
