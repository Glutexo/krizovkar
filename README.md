# Křížovkář

Křížovkář je připravovaný otevřený nástroj pro tvorbu švédských, klasických a dalších druhů křížovek.

## Stav projektu

Repozitář je v úvodní fázi. Obsahuje první verzi datového modelu a Pythonový příkaz pro vykreslení prázdné mřížky do PDF; podoba editoru bude navržena v dalších změnách.

## Zaměření

Projekt má postupně nabídnout zejména:

- tvorbu švédských křížovek s legendami přímo v mřížce,
- tvorbu klasických a dalších typů křížovek,
- otevřený datový formát oddělený od uživatelského rozhraní,
- kontrolu mřížky, výrazů a křížení,
- export pro tisk i digitální použití.

Konkrétní rozsah první funkční verze bude popsán v roadmapě před zahájením implementace.

## Datový model

Nejmenší platný dokument zatím určuje pouze rozměr mřížky:

```yaml
format: krizovkar
version: 1
grid:
  width: 15
  height: 10
```

Význam položek a pravidla dalšího rozvoje popisuje [specifikace datového modelu](docs/datovy-model.md). Úplný soubor je v [minimálním příkladu](examples/minimal.yaml) a lze ho kontrolovat pomocí [JSON Schema](src/krizovkar/schemas/krizovkar-v1.schema.json).

## Vytvoření PDF

Projekt vyžaduje Python 3.11 nebo novější. Závislosti lze nainstalovat a ukázkový YAML převést pomocí [uv](https://docs.astral.sh/uv/):

```shell
uv sync
uv run krizovkar render examples/minimal.yaml --output build/minimal.pdf
```

Výsledkem je vektorové PDF na stránce A4 s prázdnou mřížkou podle `grid.width` a `grid.height`. Bez volby `--output` vznikne PDF vedle vstupního souboru se stejným názvem. Existující soubor příkaz nepřepíše, dokud není přidána volba `--force`.

Nápovědu vypíše:

```shell
uv run krizovkar --help
```

Testy se spouštějí příkazem:

```shell
uv run python -m unittest discover -s tests
```

## Vývoj

Pravidla spolupráce jsou v [CONTRIBUTING.md](CONTRIBUTING.md). Každá dokončená logická změna se po kontrole samostatně commitne a ihned odešle na GitHub.

## Licence

Obsah repozitáře je uvolněn pod [CC0 1.0 Universal](LICENSE). Autoři se v maximálním rozsahu dovoleném právem vzdávají autorských a souvisejících práv.
