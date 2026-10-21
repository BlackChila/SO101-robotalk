# SO101 / RoboTalk: kompakter technischer Hintergrund

Diese Notizen sind Nachschlagewissen, kein Text zum vollständigen Vorlesen.
Beantworte nur den gefragten Aspekt, normalerweise in ein bis drei Sätzen.
`activeConversation` nennt den gewählten Gesprächspfad; die folgenden Alternativen
sind nicht automatisch gleichzeitig aktiv oder geladen. Stand: 21.10.2026.

## Zweck und Herkunft

RoboTalk (Repository SO101-robotalk) verbindet einen SO-101 mit einer lokalen
Browseroberfläche, Sprachgesprächen, Kamerabildern und Robotik-Inferenz. Ziel ist,
Robotik und Physical AI zugänglich und praktisch erlernbar zu machen: Menschen
können mit vergleichsweise günstiger offener Hardware experimentieren, über
LeRobot Demonstrationen sammeln und Policies trainieren oder ausprobieren.
Dieses Repository konzentriert sich auf Inferenz und Interaktion; es ist keine
vollständige Trainingsplattform. Projekt und Oberfläche stammen von BlackChila.
BlackChila (auch „Black Chila“) ist Eleni Kofekidou.

SO-101 ist ein offenes Roboterarm-Design von The Robot Studio in Zusammenarbeit
mit Hugging Face, als Nachfolger des SO-100. Der Follower hat fünf Armgelenke plus
Greifer und insgesamt sechs Motoren. Beim Teleoperieren bewegt ein Mensch einen
Leader; der Follower folgt dessen Gelenkkommandos. The Robot Studio ist der
Hardwareentwickler, LeRobot die separate Softwarebibliothek.

Hugging Face stellt offene ML-Werkzeuge und den Hub zum Teilen von Modellen,
Datensätzen und Demos bereit. LeRobot ist seine offene Python-/PyTorch-Bibliothek
für Robot Learning: Hardwareanbindung, Demonstrationsdaten, Training und
Inferenz. Ziel ist eine niedrigere Einstiegshürde in lernende Robotik.

## Architektur und Gesprächsmodelle

Das Gesprächsmodell versteht Fragen, antwortet und wählt strukturierte
Funktionsaufrufe. Das Backend führt sie aus; Text allein steuert keine Motoren.
Szenenfragen können aktuelle Kameraschnappschüsse anfordern, Bewegungsaufträge
die separate Robotik-Policy. Das Dialogmodell berechnet nicht selbst die
Gelenkaktionen. Ein Auftrag ist noch kein nachgewiesener Greif-/Platziererfolg.

Lokal: Mikrofon → Qwen3-ASR-1.7B (Spracherkennung, rund 1,7 Milliarden Parameter)
→ konfiguriertes Dialog-/Bildmodell in LM Studio → Antwort und gegebenenfalls
Funktionsaufruf → Sprachausgabe. Referenz/Dialogstandard ist Qwen3.8-27B mit rund
27 Milliarden Parametern in Q4_K_M-Quantisierung. Quantisierung senkt den
Speicherbedarf, nicht die nominelle Parameterzahl. Andere Modellschlüssel sind
möglich; bei unbekannten Varianten keine Größe raten.

„Lokal · Piper“ verwendet Piper für die neuronale Sprachausgabe auf der CPU.
Piper ist kein LLM und übernimmt weder Dialogplanung noch Robotik-Inferenz.
Es gibt keine einheitliche Milliarden-Parameterzahl für alle Piper-Stimmen.
„Lokal · Qwen“ nutzt denselben lokalen Dialog-/Werkzeugpfad mit
Qwen3-TTS-12Hz-1.7B-CustomVoice für Sprachausgabe (rund 1,7 Milliarden Parameter,
hier CUDA). Stimme und Dialogmodell sind unterschiedliche Komponenten.

„ChatGPT Realtime“ nutzt OpenAI für das direkte Audiogespräch und
Funktionsaufrufe. Die aktive Modellkennung steht im Werkzeugergebnis; deren
Parameterzahl ist hier nicht belegt. Dieser Pfad nutzt nicht Piper oder Qwen-TTS
als Stimme. Robotik-Inferenz und Motorsteuerung bleiben auf dem lokalen Rechner.

## Robotik, Kameras und Rechner

Gesprächsaufträge verwenden MolmoAct2-SO100_101 von Ai2, hier über die
LeRobot-Konvertierung: ein Vision-Language-Action-Modell mit rund 5 Milliarden
Parametern. Es verarbeitet Anweisung, Bilder und gemessenen Gelenkzustand und
erzeugt kontinuierliche Gelenkaktionen. Der Checkpoint wurde bereits auf einer
SO-100/101-Mischung nachtrainiert; es ist nicht grundsätzlich auf Pick-and-place
beschränkt. Für diesen Aufbau berichtet der Betreiber erfolgreiche
Pick-and-place-Versuche ohne zusätzliches projektspezifisches Fine-Tuning.
Das ist kein allgemeines Zuverlässigkeitsversprechen.

Molmo-Eingaben sind Overhead und eine projizierte Insta360-X5-Ansicht;
die Wrist-Kamera dient zusätzlich als Beobachter und fürs Gesichtstracking.
Ein gemeinsamer Kamera-Worker liefert Bilder. Die separate Motorsteuerung
besitzt den Arm und prüft Rückmeldungen. Stopp/Abbruch muss die gemessene Position
mit verifiziert aktiviertem Drehmoment halten; nur explizites Torque-Aus löst es.
Ein Werkzeug mit Hintergrundwissen startet keine Kamera und bewegt nichts.

Die Gesprächsoberfläche ist die Hauptseite; eine separate Steuerungsseite oder
Modellwahl für FLUX/Galaxea gehört nicht zu diesem Repository. Referenzrechner
ist Linux ARM64 mit NVIDIA GB10 (DGX Spark bzw. kompatible Workstation),
mit getrennten Python-Umgebungen und einem FastAPI-Backend samt Vite-/JavaScript-UI.
Diese Referenzbeschreibung ersetzt keinen aktuellen Hardware- oder Ladecheck.

## Belege

Lokaler Integrationsstand: `README.md`, `docs/configuration.md`,
`environments/conversation/README.md`, `environments/molmoact2/README.md`.
Offizielle Hintergründe (bei Bedarf nutzen; URLs nicht ungefragt vorlesen):

- SO-101: https://github.com/TheRobotStudio/SO-ARM100
- LeRobot: https://github.com/huggingface/lerobot
- Hugging Face Hub: https://huggingface.co/docs/hub/index
- Dialogmodell: https://huggingface.co/Qwen/Qwen3.8-27B
- ASR: https://huggingface.co/Qwen/Qwen3-ASR-1.7B
- Qwen TTS: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
- Piper: https://github.com/OHF-Voice/piper1-gpl
- MolmoAct2: https://huggingface.co/allenai/MolmoAct2-SO100_101
- LeRobot-Konvertierung: https://huggingface.co/lerobot/MolmoAct2-SO100_101-LeRobot
