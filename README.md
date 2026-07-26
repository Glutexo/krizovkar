# Křížovkář

Křížovkář je připravovaný otevřený nástroj pro tvorbu švédských, klasických a dalších druhů křížovek.

## Stav projektu

Repozitář je v úvodní fázi. Obsahuje první verzi datového modelu a Pythonový příkaz pro vykreslení prázdné nebo písmeny vyplněné mřížky do PDF; podoba editoru bude navržena v dalších změnách.

## Zaměření

Projekt má postupně nabídnout zejména:

- tvorbu švédských křížovek s legendami přímo v mřížce,
- tvorbu klasických a dalších typů křížovek,
- otevřený datový formát oddělený od uživatelského rozhraní,
- kontrolu mřížky, výrazů a křížení,
- export pro tisk i digitální použití.

Konkrétní rozsah první funkční verze bude popsán v roadmapě před zahájením implementace.

## Datový model

Křížovkář rozlišuje dva samostatné druhy YAML dokumentů:

- `kind: specification` je vstupní zadání se slovy, nápovědami, tajenkami a pravidly skládání,
- `kind: grid` je výsledná mřížka s konkrétními buňkami, kterou lze přímo vykreslit.

```text
specification → generátor (budoucí) → grid → render → PDF
```

Nejmenší platná cílová mřížka zatím určuje pouze rozměr:

```yaml
format: krizovkar
kind: grid
version: 1
grid:
  width: 15
  height: 10
```

Samostatné zadání má vlastní obálku:

```yaml
format: krizovkar
kind: specification
version: 1
```

Jeho položky pro slova a tajenky zatím nejsou definované. Význam obou dokumentů popisuje [specifikace datového modelu](docs/datovy-model.md). Strojová pravidla jsou oddělená v [JSON Schema cílové mřížky](src/krizovkar/schemas/grid-v1.schema.json) a [JSON Schema zadání](src/krizovkar/schemas/specification-v1.schema.json).

Mřížka může obsahovat řádky explicitně typovaných buněk:

```yaml
grid:
  width: 2
  height: 1
  cells:
    - [{type: letter, value: A}, {type: secret, value: H}]
```

Typ `letter` označuje běžné písmeno a `secret` písmeno patřící do tajenky. Tajenková buňka má v PDF světle šedé pozadí. V [ukázkové mřížce s tajenkou](examples/grid-secret.yaml) zvýrazněné buňky skládají slovo „TAJENKA“.

Legenda používá seznam s jedním nebo dvěma texty:

```yaml
{type: legend, texts: ["Česká řeka"]}
{type: legend, texts: ["Savec", "Pohoří"]}
```

Při dvou textech je první nahoře, druhý dole a odděluje je vodorovná čára. Text se automaticky zalomí a zmenší tak, aby se do buňky vešel. Obě varianty ukazuje [mřížka s legendami](examples/grid-legend.yaml).

Ukázka [cílové mřížky plné náhodných písmen](examples/grid-random-letters.yaml) obsahuje 15 × 10 běžných buněk. Minimální soubory jsou v příkladech [mřížky](examples/grid-minimal.yaml) a [zadání](examples/specification-minimal.yaml).

## Vytvoření PDF

Projekt vyžaduje Python 3.11 nebo novější. Závislosti lze nainstalovat a ukázkový YAML převést pomocí [uv](https://docs.astral.sh/uv/):

```shell
uv sync
uv run krizovkar render examples/grid-random-letters.yaml \
  --page-format A4 \
  --output build/random-letters.pdf
```

Volba `--page-format` přijímá `A0` až `A6`, `Letter` a `Legal`; nerozlišuje velikost písmen a její výchozí hodnota je `A4`. Výsledkem je vektorové PDF na zvoleném formátu s mřížkou a případnými písmeny podle datového modelu.

Bez volby `--output` vznikne PDF vedle vstupního souboru se stejným názvem. Existující soubor příkaz nepřepíše, dokud není přidána volba `--force`.

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
