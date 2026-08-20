# Přispívání

Děkujeme za zájem o Křížovkář. Projekt je zatím na začátku, proto mají být změny malé, srozumitelné a snadno ověřitelné.

## Pracovní postup

1. Před zahájením práce aktualizuj svou větev z GitHubu.
2. V jedné změně řeš pouze jeden logický celek.
3. Spusť všechny kontroly a testy, které jsou pro danou změnu dostupné.
4. Zkontroluj diff, zejména zda neobsahuje tajné údaje, dočasné soubory nebo nesouvisející úpravy.
5. Dokončenou změnu samostatně commitni.
6. Commit ihned odešli na GitHub pomocí `git push`.
7. Nezačínej další logickou změnu, dokud není předchozí změna úspěšně odeslaná.

Pokud push selže, nejprve vyřeš příčinu nebo nahlas blokaci. Dokončené změny se nemají hromadit pouze v lokálním repozitáři.

Před každým odevzdáním vždy spusť základní kontroly:

```shell
uv run ruff check .
uv run pytest
uv run python -m compileall -q src tests
```

## Historie a větve

- Výchozí větev je `master`.
- Pro větší práci lze použít samostatnou větev a pull request; i průběžné dokončené commity se ihned pushují na tuto větev.
- Bez výslovného souhlasu nepoužívej force push a nepřepisuj již zveřejněnou historii.
- Commit nemá obsahovat nesouvisející změny jiných přispěvatelů.

## Dokumentace

Veřejná dokumentace projektu je primárně v češtině. Uživatelské pojmy mají být konzistentní a srozumitelné i lidem bez technického zázemí.

Jazykově specifická pravidla patří do samostatných modulů v
`src/krizovkar/languages/`; česká implementace je v `czech.py`. Generátor,
renderer ani datový model nemají tato pravidla duplikovat.

České početní tvary jsou v gettext katalogu
`src/krizovkar/locale/cs/LC_MESSAGES/krizovkar.po`. Po jeho změně aktualizuj
binární katalog a zahrň oba soubory do stejného commitu:

```shell
msgfmt --check \
  --output-file=src/krizovkar/locale/cs/LC_MESSAGES/krizovkar.mo \
  src/krizovkar/locale/cs/LC_MESSAGES/krizovkar.po
```

## Licence příspěvků

Odesláním příspěvku souhlasíš s jeho uvolněním pod [CC0 1.0 Universal](LICENSE).
