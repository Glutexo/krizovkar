# Datový model

Křížovkář ukládá data jako textové dokumenty v YAML 1.2. Model je nezávislý na budoucím editoru, aby stejné soubory mohly používat různé nástroje.

Existují dva samostatné druhy dokumentů:

- zadání `specification` popisuje, co se má do křížovky vložit,
- cílová mřížka `grid` popisuje konkrétní výsledek po rozložení.

```text
specification → generování a rozložení → grid → vykreslení PDF
```

Každý druh má vlastní JSON Schema a vlastní Pythonový loader. Dokument proto vždy obsahuje povinnou položku `kind`; nástroj nemusí jeho význam odhadovat z ostatních položek.

## Cílová mřížka, verze 1

Cílová mřížka popisuje obdélníkový rozměr a případný obsah buněk:

```yaml
format: krizovkar
kind: grid
version: 1
grid:
  width: 15
  height: 10
```

### Položky

- `format` musí mít hodnotu `krizovkar` a jednoznačně označuje formát souboru.
- `kind` musí mít hodnotu `grid`.
- `version` musí mít hodnotu `1` a označuje hlavní verzi modelu cílové mřížky.
- `grid.width` je šířka mřížky v buňkách, tedy počet sloupců zleva doprava.
- `grid.height` je výška mřížky v buňkách, tedy počet řádků shora dolů.

Oba rozměry jsou povinná kladná celá čísla. Hodnota `15` proto znamená patnáct buněk, nikoli fyzickou délku nebo počet pixelů.

## Buňky s písmeny

Volitelná položka `grid.cells` obsahuje matici buněk. Vnější seznam představuje řádky shora dolů a každý vnitřní seznam buňky zleva doprava:

```yaml
grid:
  width: 3
  height: 2
  cells:
    - [{type: letter, value: Č}, {type: letter, value: CH}, {type: secret, value: Á}]
    - [{type: letter, value: O}, {type: letter, value: Ř}, {type: secret, value: J}]
```

Pokud je `cells` uvedené, musí obsahovat přesně `grid.height` řádků a každý řádek přesně `grid.width` buněk. Jeho vynechání znamená prázdnou mřížku bez určených buněk.

Podporované typy jsou:

- `type: letter` pro běžnou písmennou buňku,
- `type: secret` pro zvýrazněnou buňku, jejíž písmeno patří do tajenky.

U obou typů musí být `value` právě jedno podporované velké písmeno. Písmena si zachovávají diakritiku; české `CH` se zapisuje jako jedna hodnota a zabírá jednu buňku. Renderer odlišuje tajenkovou buňku světle šedým pozadím.

Pozice v matici jednoznačně určuje souřadnici buňky; samostatné souřadnice se proto do každé buňky neopakují. Cílová mřížka pouze označuje buňky tajenky. Její pořadí, seskupení a význam budou součástí zadání `specification`.

## Buňka legendy

Legenda neobsahuje `value`, ale seznam `texts` s jedním nebo dvěma neprázdnými texty:

```yaml
{type: legend, texts: ["Česká řeka"]}
{type: legend, texts: ["Savec", "Pohoří"]}
```

- Jeden text využije celou buňku.
- U dvou textů je první v horní a druhý v dolní polovině.
- Dvě poloviny odděluje vodorovná čára.
- Renderer text automaticky zalamuje a zmenšuje; české znaky vkládá do PDF pomocí fontu Noto Sans.

Směr odpovědi a vazba legendy na konkrétní slovo se v cílové buňce neopakují; uchovává je vyšší zadání `specification`. Experimentální generátor vytváří pro každou legendu jediný text a rozloží okolní buňky tak, aby z ní vedl právě jeden možný směr hesla doprava nebo dolů.

Generovanou mřížku dělí souvislé legendové řádky a sloupce na plně vyplněné písmenné obdélníky. Jejich průsečíky jsou nevyplňované buňky; jiné nevyplňované buňky generátor nevytváří. Každý písmenný řádek obdélníku je platné vodorovné heslo a každý jeho sloupec platné svislé heslo. Horní a levý okraj tvoří legendy s výjimkou průsečíků s další legendovou osou.

## Nevyplňovaná buňka

Buňka bez písmene a bez legendy používá typ `empty`:

```yaml
{type: empty}
```

Nemá položku `value` ani `texts`. Renderer ji v PDF označí jemným diagonálním křížkem, aby byla na první pohled rozeznatelná jako nevyplňovaná. Jde o explicitně určenou součást vyplněné matice; vynechaná položka `grid.cells` naproti tomu znamená dosud neurčenou prázdnou mřížku.

## Pomocná buňka

Pomůcka používá typ `help` a seznam `words` s alespoň jedním neprázdným textem:

```yaml
{type: help, words: [ARA, EMU, ÍRÁN]}
```

Nemá položku `value` ani `texts`. Renderer před seznam vloží tučný nadpis „Pomůcka:“, jednotlivé položky oddělí čárkou a mezerou a celý obsah automaticky zalomí a zmenší. Položky se v datovém modelu uchovávají odděleně, aby je nebylo nutné zpětně parsovat z jednoho textu.

## Zadání, verze 1

Zadání je zdrojový dokument, který popisuje rozměr mřížky a umístěná slova. Budoucí generátor z něj vytvoří cílový dokument `grid`:

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

Položky `grid` a `words` jsou navzájem provázané: jsou buď uvedené obě, nebo ani jedna. Díky tomu zůstává platná i minimální obálka rozpracovaného zadání. Je-li `words` uvedené, obsahuje alespoň jedno slovo.

### Umístěné slovo

Každá položka `words` obsahuje:

- `answer`: neprázdnou posloupnost podporovaných velkých písmen včetně diakritiky; české `CH` představuje jednu budoucí buňku,
- `start`: souřadnici prvního písmene,
- `direction`: hodnotu `horizontal` pro postup doprava nebo `vertical` pro postup dolů,
- `legend`: neprázdný text legendy,
- volitelné `in_help`: zda se odpověď vypíše v pomůcce; výchozí hodnota je `false`.

Souřadnice používají `row` a `column`, počítají se od 1 a jejich počátek leží v levém horním rohu. Řádky rostou směrem dolů a sloupce doprava. Slova se mohou křížit pouze tehdy, mají-li na společné souřadnici stejné písmeno.

### Umístění pomůcky

Obsah pomocné buňky tvoří odpovědi s `in_help: true` v pořadí, v jaké jsou uvedené ve `words`. Není-li poloha pomůcky zadaná, budoucí generátor ji po rozložení slov, legend a ostatních buněk vloží do první volné buňky. Buňky prochází po řádcích zleva doprava a shora dolů.

Vlastní polohu lze určit takto:

```yaml
help:
  position: {row: 1, column: 7}
```

Blok `help` je platný jen tehdy, když má alespoň jedno slovo `in_help: true`. Výslovná souřadnice musí ležet uvnitř mřížky a nesmí být obsazená písmenem. Úplnou kontrolu proti buňkám vzniklým při generování provede generátor.

Loader již ověřuje rozměry, rozsah slov, shodu písmen na kříženích a základní platnost výslovné polohy pomůcky. Samotný převod `specification` na `grid` zatím není součástí příkazu `render`.

## Validace

Strojová pravidla jsou v samostatných schématech pro [cílovou mřížku](../src/krizovkar/schemas/grid-v1.schema.json) a [zadání](../src/krizovkar/schemas/specification-v1.schema.json). Schémata odmítají chybějící, neznámé a chybně napsané položky i nulové, záporné nebo neceločíselné rozměry. Pythonové loadery navíc kontrolují vztahy, které závisejí na více částech dokumentu.

Minimální dokumenty jsou v příkladech [cílové mřížky](../examples/grid-minimal.yaml) a [zadání](../examples/specification-minimal.yaml).

Vyšší zadání ukazuje [příklad s umístěnými slovy a automatickou pomůckou](../examples/specification-placed-words.yaml).

Vyplněná cílová mřížka je v [příkladu s náhodnými písmeny](../examples/grid-random-letters.yaml).

Smíšené typy buněk ukazuje [příklad s tajenkou](../examples/grid-secret.yaml).

Česká písmena s diakritikou a jednopísmenné `CH` ukazuje [mřížka s českými písmeny](../examples/grid-czech-letters.yaml).

Jednoduchou i dvojitou legendu ukazuje [příklad s legendami](../examples/grid-legend.yaml).

Nevyplňované buňky ukazuje [příklad s diagonálními křížky](../examples/grid-empty.yaml).

Pomocnou buňku ukazuje [příklad se seznamem slov](../examples/grid-help.yaml).

## Rozvoj formátu

- Nová data se mají přidávat pod srozumitelně pojmenované položky, nikoli odvozovat z pořadí zápisu v YAML.
- Zpětně kompatibilní rozšíření mohou zůstat ve verzi `1`; nekompatibilní změna vyžaduje novou hlavní verzi.
- Příklady, dokumentace a příslušné schéma se při změně modelu aktualizují společně.
