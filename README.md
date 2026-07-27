# Křížovkář

Křížovkář je připravovaný otevřený nástroj pro tvorbu švédských, klasických a dalších druhů křížovek.

## Stav projektu

Repozitář je v úvodní fázi. Obsahuje první verzi datového modelu, experimentální generátor švédské mřížky z JSON slovníku a vykreslení výsledku do PDF. Podoba editoru bude navržena v dalších změnách.

## Zaměření

Projekt má postupně nabídnout zejména:

- tvorbu švédských křížovek s legendami přímo v mřížce,
- tvorbu klasických a dalších typů křížovek,
- otevřený datový formát oddělený od uživatelského rozhraní,
- kontrolu mřížky, výrazů a křížení,
- export pro tisk i digitální použití.

Experimentální generátor ověřuje základní práci se slovníkem a křížením; konkrétní rozsah první funkční verze bude popsán v roadmapě.

## Datový model

Křížovkář rozlišuje dva samostatné druhy YAML dokumentů:

- `kind: specification` je vstupní zadání se slovy, nápovědami, tajenkami a pravidly skládání,
- `kind: grid` je výsledná mřížka s konkrétními buňkami, kterou lze přímo vykreslit.

```text
specification → generátor (budoucí) → grid → render → PDF
slovník → experimentální generátor → grid → render → PDF
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

Samostatné zadání popisuje rozměr a umístěná slova:

```yaml
format: krizovkar
kind: specification
version: 1
grid:
  width: 7
  height: 6
words:
  - answer: LABE
    start: {row: 2, column: 2}
    direction: horizontal
    legend: Česká řeka
  - answer: LES
    start: {row: 2, column: 2}
    direction: vertical
    legend: Porost stromů
    in_help: true
```

Souřadnice se počítají od 1 z levého horního rohu a `start` označuje první písmeno. Směr je `horizontal` nebo `vertical`; vynechané `in_help` znamená `false`. Pokud je alespoň jedno slovo v pomůcce, generátor pro ni použije první volnou buňku, není-li zadané vlastní `help.position`. Ucelenou podobu ukazuje [zadání s umístěnými slovy](examples/specification-placed-words.yaml).

Zadání rozlišuje tajenku složenou z vybraných polí a tajenku, která je souvislým heslem označeným textem „Tajenka“:

```yaml
secrets:
  - type: cells
    arrows: true
    cells:
      - {row: 2, column: 2}
      - {row: 2, column: 3}
      - {row: 2, column: 4}
      - {row: 2, column: 5}
      - {row: 3, column: 5}
      - {row: 4, column: 5}
  - type: word
    answer: KŘÍŽOVKÁŘ
    start: {row: 5, column: 2}
    direction: horizontal
```

U `type: cells` určuje pořadí souřadnic také pořadí čtení a každé vybrané pole musí obsahovat písmeno. Tato podoba nemá vlastní legendu. Volitelné `arrows: true` vyžaduje cestu přes sousední pole a přidá malou odchozí šipku na její začátek a na každé místo změny směru. Znak má stejné proporce a tah jako šipky u legend. Bez této volby mohou pole zůstat libovolně rozmístěná. `type: word` se umisťuje a kříží stejně jako běžné heslo, ale jeho písmena budou zvýrazněná jako tajenka. Odpověď zadává autor přímo a nemusí být ve slovníku; vynechaná `legend` dostane automaticky text `Tajenka`. Obě podoby ukazuje [zadání s tajenkami](examples/specification-secrets.yaml).

Význam obou dokumentů popisuje [specifikace datového modelu](docs/datovy-model.md). Strojová pravidla jsou oddělená v [JSON Schema cílové mřížky](src/krizovkar/schemas/grid-v1.schema.json) a [JSON Schema zadání](src/krizovkar/schemas/specification-v1.schema.json).

Mřížka může obsahovat řádky explicitně typovaných buněk:

```yaml
grid:
  width: 3
  height: 1
  cells:
    - [{type: secret, value: Č, arrow: right}, {type: letter, value: CH}, {type: letter, value: Á}]
```

Typ `letter` označuje běžné písmeno a `secret` písmeno patřící do tajenky. České `CH` zabírá jednu buňku stejně jako samostatné písmeno a písmena si zachovávají diakritiku. Tajenková buňka má v PDF světle šedé pozadí a může mít jednu rohovou `arrow` ve směru `up`, `right`, `down` nebo `left`. Jde o jinou značku než seznam `arrows` v legendové buňce. Cílová mřížka už nerozlišuje, zda tajenku určil seznam polí, nebo souvislé heslo; u druhé varianty navíc obsahuje legendovou buňku s textem „Tajenka“. Zápis ukazuje [mřížka s českými písmeny](examples/grid-czech-letters.yaml); [ukázková cesta se šipkami](examples/grid-secret-arrows.yaml) mění směr dvakrát.

Legenda používá neprázdný seznam textů a může u nich výslovně uvést směrové šipky:

```yaml
{type: legend, texts: ["Česká řeka"]}
{type: legend, texts: ["Savec", "Pohoří"], arrows: [right, down]}
```

Formát počet textů neomezuje estetickým pravidlem. Renderer rozdělí buňku na stejně vysoké části v pořadí shora dolů; případné šipky `right` a `down` přiřadí textům ve stejném pořadí. Text se automaticky zalomí a zmenší tak, aby se do buňky vešel. Slovo, které se vejde celé na samostatný řádek, renderer nedělí. Delší česká slova dělí podle slovníku knihovny Pyphen; neláme je na libovolném znaku. Jednopísmenné souhláskové předložky `k`, `s`, `v` a `z` se při vykreslení spojí s následujícím výrazem nezalomitelnou mezerou. Jednoduchou a dvojitou variantu ukazuje [mřížka s legendami](examples/grid-legend.yaml).

Explicitně nevyplňovaná buňka nemá písmeno ani legendu:

```yaml
{type: empty}
```

V PDF ji označuje jemný diagonální křížek. Tím se liší od dosud neurčené prázdné buňky v mřížce bez položky `cells`. Použití ukazuje [mřížka s nevyplňovanými buňkami](examples/grid-empty.yaml).

Pomocná buňka obsahuje jeden nebo více výrazů:

```yaml
{type: help, words: [ARA, EMU, ÍRÁN]}
```

V PDF renderer doplní tučný nadpis „Pomůcka:“ a položky vypíše za ním oddělené čárkou a mezerou. Celý text automaticky zalomí a zmenší tak, aby se vešel do buňky. Výsledek ukazuje [mřížka s pomůckou](examples/grid-help.yaml).

Ukázka [cílové mřížky plné náhodných písmen](examples/grid-random-letters.yaml) obsahuje 15 × 10 běžných buněk. Minimální soubory jsou v příkladech [mřížky](examples/grid-minimal.yaml) a [zadání](examples/specification-minimal.yaml).

## Pokusné generování

Generátor přijímá slovník jako JSON objekt. Klíčem je heslo složené z podporovaných velkých písmen včetně diakritiky a hodnotou neprázdný seznam možných legend v preferovaném pořadí:

```json
{
  "OCHOČENÁ": ["Zkrocená"],
  "ŘEKA": ["Vodní tok"]
}
```

Pokusnou mřížku lze vytvořit a následně vykreslit:

```shell
uv run krizovkar generate slovnik.json \
  --width 15 \
  --height 10 \
  --seed 10 \
  --output build/generated-grid.yaml
uv run krizovkar render build/generated-grid.yaml \
  --output build/generated-grid.pdf
```

Stejný slovník, rozměr a seed vytvoří stejnou mřížku. Generátor rozdělí plochu legendovými řádky a sloupci na písmenné obdélníky a všechny je vyplní platnými křížícími se hesly. Každá písmenná buňka proto patří jednomu vodorovnému i jednomu svislému výrazu; prázdné zůstávají pouze průsečíky legendových řádků a sloupců.

Současný experiment vyplňuje každý takový obdélník samostatně. Pokud jich vznikne více, kvalitativní validace upozorní, že výsledná slova tvoří oddělené ostrovy; propojení bloků bude úkolem další verze generátoru.

Legendy pokrývají horní a levou stranu každého písmenného bloku. Na horním okraji chybí legenda jen ve sloupci s dalšími vnitřními legendami a na levém okraji jen v řádku s dalšími vnitřními legendami. Každá legenda má jediný text a právě jeden možný směr navazujícího hesla, takže nepotřebuje šipku. První experimentální verze zatím nevytváří tajenku ani pomůcku a nehodnotí jazykovou kvalitu hesel. Zdrojový slovník není součástí projektu; uživatel musí mít právo jeho obsah použít.

## Validace

Datový formát a pravidla dobré křížovky jsou dvě oddělené vrstvy. Příkaz `validate` nejprve ověří, zda lze YAML bezpečně načíst jako cílovou mřížku, a potom jej posoudí podle současného profilu husté švédské křížovky:

```shell
uv run krizovkar validate build/generated-grid.yaml
```

Chyba znamená neplatný nebo vnitřně rozporný datový model a příkaz skončí návratovým kódem `2`. Varování znamená platnou mřížku, kterou lze dál zpracovat a vykreslit, ale porušuje některé pravidlo kvality; návratový kód zůstává `0`.

Profil nyní varuje zejména před směrovými šipkami v legendách, nesouladem počtu textů a navazujících směrů, heslem bez bezprostředně předcházející legendy a oddělenými písmennými ostrovy. Rohové šipky tajenky toto varování nevyvolávají. Jednoduchá legenda má jeden text a směr; dvojitá má dva texty v pořadí doprava a dolů. Tato pravidla nejsou omezením obecného formátu a jiné druhy křížovek mohou v budoucnu používat jiný profil.

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
