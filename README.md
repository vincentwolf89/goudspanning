# goudspanning

Dagelijkse spanningsmeter voor goud (XAUUSD), elke werkdag rond 07:00 Europe/Amsterdam bijgewerkt.

- `spanning.json` - volledige uitslag: vijf gemeten signalen (kansmodel grote dag, GVZ, reële rente, 250-daagse bodem/top, aandelenstress),
  een nieuwsniveau 0-2 met korte analyse per high-impact bericht, en een pauze-advies per bericht.
- `spanning.txt` - platte versie voor een MT5-EA (SLEUTEL=waarde).
- `spanning_historie.csv` - één regel per handelsdag.

Niveau: RUSTIG / OPLETTEN / ALARM. De cijferscore (0-5) is geijkt op 2010-2026: bij 0 volgde een dag met >= 3% bereik in 2% van de
gevallen, bij 3 in 29%, bij 4 in 52%. De score zegt iets over de kans op een grote beweging, niet over de richting.

Informatief, geen beleggingsadvies.
