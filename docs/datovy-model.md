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

Pozice v matici jednoznačně určuje souřadnici buňky; samostatné souřadnice se proto do každé buňky neopakují. Cílová mřížka pouze označuje buňky tajenky. Jejich pořadí, seskupení a případnou vlastní legendu uchovává zdrojové zadání `specification`.

## Buňka legendy

Legenda neobsahuje `value`, ale neprázdný seznam `texts` s neprázdnými texty. Volitelné `arrows` může obsahovat směrové šipky:

```yaml
{type: legend, texts: ["Česká řeka"]}
{type: legend, texts: ["Savec", "Pohoří"], arrows: [right, down]}
```

- Texty se vykreslují do stejně vysokých částí v pořadí shora dolů.
- Části oddělují vodorovné čáry.
- Šipky `right` a `down` se přiřazují textům ve stejném pořadí.
- Renderer text automaticky zalamuje a zmenšuje; české znaky vkládá do PDF pomocí fontu Noto Sans.

Počet textů ani přítomnost šipek nejsou omezením datového formátu. Experimentální generátor přesto vytváří pro každou legendu jediný text bez šipky a rozloží okolní buňky tak, aby z ní vedl právě jeden možný směr hesla doprava nebo dolů.

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

Položka `grid` se uvádí společně alespoň s jednou z položek `words` nebo `secrets`. Díky tomu zůstává platná minimální obálka rozpracovaného zadání, ale úplné zadání může obsahovat běžná slova, tajenky nebo obojí. Každý uvedený seznam obsahuje alespoň jednu položku.

### Umístěné slovo

Každá položka `words` obsahuje:

- `answer`: neprázdnou posloupnost podporovaných velkých písmen včetně diakritiky; české `CH` představuje jednu budoucí buňku,
- `start`: souřadnici prvního písmene,
- `direction`: hodnotu `horizontal` pro postup doprava nebo `vertical` pro postup dolů,
- `legend`: neprázdný text legendy,
- volitelné `in_help`: zda se odpověď vypíše v pomůcce; výchozí hodnota je `false`.

Souřadnice používají `row` a `column`, počítají se od 1 a jejich počátek leží v levém horním rohu. Řádky rostou směrem dolů a sloupce doprava. Slova se mohou křížit pouze tehdy, mají-li na společné souřadnici stejné písmeno.

### Tajenky

Volitelný seznam `secrets` uchovává jednu nebo více tajenek. Povinné `type` rozlišuje dva způsoby jejich určení.

Tajenka `type: cells` obsahuje neprázdný seznam `cells`:

```yaml
secrets:
  - type: cells
    cells:
      - {row: 2, column: 2}
      - {row: 2, column: 5}
      - {row: 4, column: 2}
```

Souřadnice jsou uvedené přímo v pořadí, v jaké se tajenka čte. Nesmějí se v jednom seznamu opakovat, musí ležet uvnitř mřížky a odkazovat na písmena některého umístěného běžného nebo tajenkového slova. Pole nemusejí tvořit přímku ani spolu sousedit.

Tajenka `type: word` je souvislé vodorovné nebo svislé slovo s vlastní legendou:

```yaml
secrets:
  - type: word
    answer: AMONIT
    start: {row: 5, column: 2}
    direction: horizontal
    legend: Zkamenělý hlavonožec
```

Položky `answer`, `start`, `direction` a `legend` mají stejný význam jako u běžného umístěného slova. Tajenkové slovo se už neopakuje ve `words`; samo obsazuje písmenná pole, může se křížit s ostatními slovy a při převodu do cílové mřížky dostane legendovou buňku a buňky `type: secret`.

Obě varianty mohou být v jednom zadání. Cílový dokument `grid` je při vykreslení zobrazuje stejným zvýrazněním; jejich původní definici zachovává pouze `specification`.

### Umístění pomůcky

Obsah pomocné buňky tvoří odpovědi s `in_help: true` v pořadí, v jaké jsou uvedené ve `words`. Není-li poloha pomůcky zadaná, budoucí generátor ji po rozložení slov, legend a ostatních buněk vloží do první volné buňky. Buňky prochází po řádcích zleva doprava a shora dolů.

Vlastní polohu lze určit takto:

```yaml
help:
  position: {row: 1, column: 7}
```

Blok `help` je platný jen tehdy, když má alespoň jedno slovo `in_help: true`. Výslovná souřadnice musí ležet uvnitř mřížky a nesmí být obsazená písmenem. Úplnou kontrolu proti buňkám vzniklým při generování provede generátor.

Loader již ověřuje rozměry, rozsah běžných i tajenkových slov, shodu písmen na kříženích, obsazenost vybraných tajenkových polí a základní platnost výslovné polohy pomůcky. Samotný převod `specification` na `grid` zatím není součástí příkazu `render`.

## Validace

Strojová pravidla jsou v samostatných schématech pro [cílovou mřížku](../src/krizovkar/schemas/grid-v1.schema.json) a [zadání](../src/krizovkar/schemas/specification-v1.schema.json). Schémata odmítají chybějící, neznámé a chybně napsané položky i nulové, záporné nebo neceločíselné rozměry. Pythonové loadery navíc kontrolují vztahy, které závisejí na více částech dokumentu.

Validace cílové mřížky rozlišuje dvě závažnosti:

- `error` označuje chybu datového modelu, kvůli které dokument nelze bezpečně načíst nebo dále zpracovat,
- `warning` označuje formálně platnou mřížku, která může být hůře čitelná nebo nesplňuje zvolená pravidla kvality.

Příkaz `krizovkar validate` při chybě vrací kód `2`. Samotná varování vypíše, ale vrací kód `0`, takže neblokují vykreslení ani další zpracování. Každá položka reportu obsahuje závažnost, strojově čitelný kód, cestu k místu v dokumentu a českou zprávu.

Současný kvalitativní profil je určený pro hustou švédskou mřížku bez šipek. Každý nový vodorovný či svislý běh písmen musí mít bezprostředně před sebou legendovou buňku. Počet jejích textů odpovídá počtu navazujících směrů: jednoduchá legenda má jeden text, dvojitá dva texty v pořadí doprava a dolů. Všechny běžné a tajenkové písmenné buňky zároveň musí tvořit jedinou oblast propojenou společnými hranami; legendy, pomůcky a nevyplňované buňky jsou její hranice. Jde o neblokující formální pravidla pro dobrý výsledek, nikoli o omezení obecného datového formátu. Jiný druh křížovky proto může později použít jiný profil nad stejnými daty.

Minimální dokumenty jsou v příkladech [cílové mřížky](../examples/grid-minimal.yaml) a [zadání](../examples/specification-minimal.yaml).

Vyšší zadání ukazuje [příklad s umístěnými slovy a automatickou pomůckou](../examples/specification-placed-words.yaml).

Oba způsoby určení tajenky ukazuje [příklad s vybranými poli a tajenkovým slovem](../examples/specification-secrets.yaml).

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
