# Datový model

Křížovkář ukládá data jako textové dokumenty v YAML 1.2. Model je nezávislý na budoucím editoru, aby stejné soubory mohly používat různé nástroje.

Existují tři samostatné druhy dokumentů:

- zadání `specification` popisuje, co se má do křížovky vložit,
- editovatelná křížovka `crossword` popisuje role buněk, místa pro hesla a
  jejich případně doplněný obsah; v libovolném stavu může sloužit jako šablona,
- cílová mřížka `grid` popisuje konkrétní role buněk a volitelně jejich obsah.

```text
umístěné specification + volba rozvržení → generování šablony → crossword
rozměr + volba rozvržení → generování šablony → crossword
crossword + ruční doplňování → crossword → grid → LaTeX → PDF
crossword + slovník → plnění → crossword → grid → LaTeX → PDF
```

LaTeXový zdroj není dalším druhem YAML dokumentu a nemá položku `kind`.
Jde o textový export cílové mřížky, který lze upravit a přeložit LuaLaTeXem
do PDF.

Každý druh má vlastní JSON Schema a vlastní Pythonový loader. Dokument proto vždy obsahuje povinnou položku `kind`; nástroj nemusí jeho význam odhadovat z ostatních položek.

Položka `kind` rozlišuje strukturu a účel dokumentu, nikoli míru vyplnění ani
švédskou, čárkovanou nebo jinou podobu křížovky. Všechny používají stejné
zadání i stejný model cílové mřížky. Způsob uvedení legendy je vlastnost
konkrétního rozložení a jednotlivá hesla v jedné mřížce mohou používat různé
způsoby.

## Editovatelná křížovka, verze 1

Dokument `kind: crossword` může být prázdný, rozpracovaný nebo hotový. Míra
vyplnění není součástí jeho typu: nevyplněná i částečně vyplněná křížovka
může sloužit jako šablona a hotová křížovka pouze nemá žádné zbývající místo
k doplnění. Hustá nevyplněná křížovka obsah odpovědí nezná:

```yaml
format: krizovkar
kind: crossword
version: 1
grid:
  width: 3
  height: 1
  cells:
    - [{type: letter}, {type: letter}, {type: letter}]
slots:
  - id: h1
    start: {row: 1, column: 1}
    direction: horizontal
    length: 3
```

Povinná matice `grid.cells` rozlišuje čtyři role:

- `type: letter` je dosud nevyplněná písmenná buňka,
- `type: legend` rezervuje buňku pro jednu nebo dvě budoucí vepsané legendy,
- `type: help` rezervuje buňku pro slova pomůcky,
- `type: empty` je nevyplňovaná buňka.

Každý `slot` popisuje jedno budoucí heslo. Povinné `id` je v dokumentu jedinečné, `start` používá souřadnice od 1, `direction` určuje směr doprava nebo dolů a `length` je počet buněk. Stejně jako v ostatních dokumentech zabírá české `CH` jednu buňku.

Volitelné `clue_placement` určuje umístění legendy. Hodnota `inline` používá
legendovou buňku bezprostředně vlevo od vodorovného slotu nebo nad svislým
slotem; její souřadnice se vždy odvodí ze `start` a `direction`. Hodnota
`external` znamená budoucí vnější číslovanou legendu a je výchozí, takže ji
lze vynechat. Stejný model tím podporuje švédské, klasické i smíšené
rozložení bez opakování odvoditelné souřadnice.

Křížovka převedená ze zadání může slotu přidat položku `answer`
s doplněnou odpovědí a volitelnou položku `clue` s její legendou.
Vynechané `clue` použije jako legendu samotnou hodnotu `answer`. Samostatné
`clue` bez `answer` není platné a počet písmenných polí `answer` musí
odpovídat `length`.
Volitelné `in_help: true` zařadí odpověď do jediné buňky `type: help`.
Křížící se odpovědi musí mít na společném poli stejné písmeno. Ucelený
zápis ukazuje [šablona ze zadání](../examples/template-from-specification.yaml).

### Připravená tajenka

Volitelný seznam `secrets` přiřadí části tajenky konkrétním slotům:

```yaml
secrets:
  - words: [KOMU, SE, NELENÍ]
    parts:
      - {slot: h3, word_count: 2}
      - {slot: h8, word_count: 1}
    prompt:
      text: 'Dokončete lidové rčení.'
      placement: above
      alignment: left
```

Pořadí `parts` je současně pořadí částí tajenky. Každý odkaz `slot` musí existovat a jeden slot smí patřit nejvýše jedné části. Seznam `words` uchovává jednotlivá slova bez mezer a interpunkce. Tím zůstávají známé všechny povolené švy, přestože do buněk se slova zapíší spojeně.

Část tajenky určená vybranými poli místo `slot` uchová seznam
`cells`. Každá souřadnice musí odkazovat na `type: letter`. Volitelné
`arrows: true` zachová pořadí souvislé cesty ze zadání; bez něj jde o
samostatná pole čtená po řádcích. Jedna tajenka smí oba druhy částí
kombinovat.

Je-li znění tajenky známé, povinné `word_count` u každé části
odkazující na slot určuje počet po sobě jdoucích slov v daném slotu. Součet
musí odpovídat počtu `words` a spojená slova musí přesně zaplnit délku
slotu; žádné rozdělení proto nemůže vzniknout uvnitř slova. Neznámá
tajenka vynechá `words` i všechna `word_count`; délky připravených částí
pak určují samotné sloty. Volitelné `prompt` má stejný význam jako zadání
tajenky v dokumentech `specification` a `grid`. Ucelený příklad je v
[šabloně se známou tajenkou](../examples/template-secret.yaml).

Loader navíc kontroluje rozměr matice, přesah slotů, jejich překryvy ve
stejném směru a vazby na role buněk. Každá písmenná buňka musí patřit
alespoň jednomu slotu a každou legendovou buňku musí používat alespoň jeden
slot. Buňka pomůcky smí být nejvýše jedna a vyžaduje alespoň jeden pevný
slot s `in_help: true`. Ucelený zápis je v
[nevyplněné šabloně](../examples/template-unfilled.yaml).

Příkaz `template` s pozičním vstupem načte `specification` a vytvoří z
každého umístěného slova vyplněný slot. Výchozí `--layout swedish` vyžaduje
pro každé slovo volnou legendovou buňku bezprostředně před jeho začátkem.
`--layout numbered` ponechá legendu vně mřížky. Volná pole se stanou
`type: empty`; potřebnou pomůcku převod vloží na výslovnou pozici nebo do
první volné buňky po řádcích. Tajenková slova se stanou pevnými sloty a
tajenky z vybraných polí zůstanou samostatnými částmi `cells`.

Bez pozičního vstupu vytváří `template` hustou nevyplněnou šablonu
bez slovníku. Švédské rozvržení používá legendové osy a písmenné bloky;
číslované ponechá celou plochu písmennou a rozdělí ji silnými předěly.
Bez další volby se vybere první deterministicky seřazená varianta;
`--randomize` pořadí variant pseudonáhodně změní a `--seed` zachová
opakovatelnost. `--empty` vytvoří místo husté masky jednoduchý platný základ
bez vnitřních předělů. Nelze jej kombinovat se seedem ani volbami tajenky.
Vodorovné sloty dostávají identifikátory `h1`, `h2`, … v pořadí shora dolů
a zleva doprava; svislé obdobně `v1`, `v2`, … Volby tajenky mohou určit
celkovou délku, pevné délky částí, konkrétní seznam slov s automatickým
dělením nebo konkrétní pevné části. Generátor pro ně vybírá navzájem se
nepřekrývající sloty. U známého textu ukládá výsledné `word_count` a vybrané
sloty rovnou vyplní odpovědí i legendou tajenky. Prohledává seřazené varianty
délek 3 až 8 a vybere první, která obsahuje všechny požadované délky a dovolí
jejich umístění.

Příkaz `fill` přijímá libovolnou platnou křížovku a slovník. Doplněné
sloty použije jako počáteční omezení. Pomocí zpětného prohledávání přiřadí
každému zbývajícímu běžnému slotu jiné heslo správné délky a průběžně
omezuje kandidáty podle již známých písmen na kříženích. Dosud prázdné
tajenkové sloty vyplní přímo, bez hledání odpovědi ve slovníku; už vyplněnou
tajenku zachová a její písmena použije jako další pevná omezení. Neznámou
rezervovanou tajenku musí doplnit konkrétní text; není-li v dokumentu
rezervace, `fill` vhodné sloty automaticky vybere. Rozdělení je přípustné
jen tehdy, pokud každá část končí na hranici slova.

Vstupem i výsledkem `fill` je dokument `kind: crossword`; každému nově
vyplněnému slotu přibude `answer` a `clue`. Rozvržení, tajenky a pomůcka
zůstanou editovatelné a celou křížovku lze znovu použít jako šablonu. U hotové
křížovky není co doplnit. Seed určuje pořadí kandidátů a zachovává
opakovatelnost výsledku.

Příkaz `grid` převádí platnou křížovku na cílovou mřížku bez slovníku. Role
`letter`, `legend`, `help` a `empty` zachová, u číslovaných slotů doplní čísla
začátků a silné mezislovní předěly a připravené tajenky převede na buňky
`secret`. Přenese také jejich zobáčky a `prompt`. Nevyplněné sloty zůstanou
prázdné; doplněné sloty naopak vloží svá písmena a legendy a `in_help` naplní
pomůcku. Tajenkové sloty označí jako `type: secret`. Vepsané legendy
převezmou texty přiřazených hesel; sloty s `clue_placement: external` se
převedou na číslovaná hesla s vnějšími legendami. Společný začátek vodorovného
a svislého slotu sdílí jedno číslo. Samotná `secrets.words` u slotu bez
pevného `answer` se při tomto
převodu dál nezveřejňují. Příkazy `latex` a `render` umějí stejný převod
provést automaticky, dostanou-li přímo `kind: crossword`. První z
nich vypíše upravitelný LaTeX, druhý stejný zdroj přeloží LuaLaTeXem do PDF.

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
    - [{type: secret, value: Č, arrow: right}, {type: letter, value: CH}, {type: letter, value: Á}]
    - [{type: letter, value: O}, {type: letter, value: Ř}, {type: secret, value: J}]
```

Pokud je `cells` uvedené, musí obsahovat přesně `grid.height` řádků a každý
řádek přesně `grid.width` buněk. Jeho vynechání znamená prázdnou mřížku bez
určených rolí buněk. Mřížka vytvořená z křížovky naopak role obsahuje, ale její
písmena a legendy mohou zůstat nevyplněné.

Podporované typy jsou:

- `type: letter` pro běžnou písmennou buňku,
- `type: secret` pro zvýrazněnou buňku, jejíž písmeno patří do tajenky.

U obou typů je `value` volitelné. Jeho vynechání znamená dosud nevyplněné
písmenné pole; uvedená hodnota musí být právě jedno podporované velké písmeno.
Písmena si zachovávají diakritiku a české `CH` se zapisuje jako jedna hodnota
a zabírá jednu buňku. Renderer neznámou hodnotu ponechá prázdnou a tajenkovou
buňku odliší světle šedým pozadím. Jen `type: secret` může navíc obsahovat
odchozí `arrow` ve směru `up`, `right`, `down` nebo `left`; vykreslí se jako
plný černý trojúhelníkový zobáček se základnou na hraně pole a špičkou ve směru
pokračování.

Pozice v matici jednoznačně určuje souřadnici buňky; samostatné souřadnice se proto do každé buňky neopakují. Cílová mřížka pouze označuje buňky tajenky. Jejich pořadí a seskupení uchovává zdrojové zadání `specification`.

### Zadání tajenky vně mřížky

Volitelný kořenový seznam `secret_prompts` uchovává texty zadání jedné nebo více tajenek:

```yaml
secret_prompts:
  - text: 'Lidové rčení: „Komu se nelení, tomu se …“'
    placement: above
    alignment: left
```

Povinné `text` musí obsahovat alespoň jeden neprázdný znak. `placement` určuje umístění `above` nad mřížkou nebo `below` pod ní a `alignment` zarovná text `left` doleva nebo `right` doprava vzhledem k šířce mřížky. Výchozí hodnoty jsou `above` a `left`. Pořadí položek se zachovává; každé zadání je samostatný odstavec. Renderer text automaticky zalomí na šířku mřížky a započítá jej do vystředění celého obsahu stránky. Spodní zadání jsou mezi mřížkou a případnými číselnými legendami.

Zadání tajenky není legendou hesla. `secret_prompts` proto nijak neomezuje současné použití legendových buněk ani kořenových číselných `clues`.

### Čísla, mezislovní předěly a vnější legendy

Běžná i tajenková písmenná buňka může obsahovat kladné celé `number`. Číslo označuje začátek vodorovného slova, svislého slova nebo obou současně. V jedné mřížce smí být každé číslo pouze v jedné buňce. Doporučené klasické číslování prochází počáteční pole po řádcích zleva doprava a shora dolů.

Pokud v jednom řádku nebo sloupci bez nevyplňované buňky následuje další slovo, konec předchozího slova vyznačí `bars`:

```yaml
{type: letter, value: K, number: 3, bars: [right, bottom]}
```

Hodnota `right` označuje silný předěl mezi touto buňkou a buňkou napravo, `bottom` předěl mezi touto buňkou a buňkou pod ní. Předěly jsou určené pouze pro vnitřní hrany mřížky; její vnější rám se do buněk nezapisuje. Renderer používá pro všechny tyto předěly i rám jedinou silnější tloušťku čáry.

Volitelný kořenový seznam `clues` uchovává legendy mimo mřížku:

```yaml
clues:
  - number: 1
    direction: horizontal
    text: Prudký hod
  - number: 1
    direction: vertical
    text: Prudký hod
```

Každá legenda odkazuje na existující očíslovanou písmennou buňku a dvojice `number` a `direction` se nesmí opakovat. Začíná-li takto popsané slovo uvnitř souvislého písmenného řádku nebo sloupce, musí je od předchozího slova oddělovat odpovídající silný předěl. Společné počáteční pole může mít pod jedním číslem jednu vodorovnou a jednu svislou legendu. Samotné číslo legendu nevyžaduje; tím lze označit například tajenku bez vlastní nápovědy.

Čísla, předěly a kořenové `clues` neurčují druh celého dokumentu. Ve stejné mřížce mohou být současně buňky `type: legend`; jedno heslo tak může mít vepsanou legendu a jiné legendu číselnou. Formát nezakazuje ani oba způsoby u téhož hesla. Ucelenou kombinaci ukazuje [příklad se smíšenými legendami](../examples/grid-mixed-clues.yaml).

Renderer sází číslo do levého horního rohu buňky a vnější legendy pod mřížku do samostatných sloupců „Vodorovně“ a „Svisle“. Zadání tajenek, čísla, legendy, předěly, zvýraznění tajenky a tajenkové šipky zůstávají viditelné i při vykreslení nevyplněné varianty.

## Buňka legendy

Legenda neobsahuje `value`. Volitelný neprázdný seznam `texts` uchovává již
známé neprázdné texty. Hodnota `null` rezervuje jednu dosud nevyplněnou část,
takže například `[null, null]` zachová vodorovné rozdělení dvojité legendy.
Vynechání celého `texts` znamená prázdnou buňku bez určeného počtu částí.
Volitelné `arrows` lze uvést jen společně s `texts`:

```yaml
{type: legend}
{type: legend, texts: [null, null]}
{type: legend, texts: ["Česká řeka"]}
{type: legend, texts: ["Savec", "Pohoří"], arrows: [right, down]}
```

- Texty se vykreslují do stejně vysokých částí v pořadí shora dolů.
- Části oddělují vodorovné čáry.
- Šipky `right` a `down` se přiřazují textům ve stejném pořadí.
- LaTeX text automaticky zalamuje a podle prostoru zmenšuje; české znaky sází LuaLaTeX pomocí fontu Latin Modern Sans.

Počet textů ani shoda počtu textů a šipek nejsou estetickým omezením datového
formátu. Převod švédské šablony do cílové mřížky přesto vytváří pro každou
vyplněnou vepsanou legendu jediný text bez šipky; generátor šablonu rozloží
tak, aby z legendy vedl právě jeden možný směr hesla doprava nebo dolů.

Švédskou mřížku dělí souvislé legendové řádky a sloupce na písmenné
obdélníky. Jejich průsečíky jsou nevyplňované buňky. Každý písmenný řádek
obdélníku je vodorovný slot a každý jeho sloupec svislý slot. Horní a levý
okraj tvoří legendy s výjimkou průsečíků s další legendovou osou. Číslované
rozvržení naproti tomu používá všechny buňky pro písmena, začátky slotů čísluje
po řádcích a hranice dalších slov označuje pomocí `bars`. Až plnění slovníkem
doplní jejich hodnoty a texty `clues`.

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

Zadání je zdrojový dokument, který popisuje rozměr mřížky a umístěná
slova. Příkaz `template` z něj vytvoří křížovku použitelnou jako šablona,
kterou lze převést na cílový dokument `grid`:

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
- volitelné `legend`: neprázdný text legendy; při vynechání se použije
  samotné `answer`,
- volitelné `in_help`: zda se odpověď vypíše v pomůcce; výchozí hodnota je `false`.

Tento popis hesla je společný pro švédské i čárkované rozložení.
`specification` neurčuje, zda se text `legend` později zapíše do samostatné
legendové buňky, nebo jako číselná legenda mimo mřížku. Legendové buňky
však zabírají souřadnice, a proto může stejné zadání vyhovět rozměru
čárkované mřížky, ale po vložení vepsaných legend už nevyhovět rozměru
švédské mřížky. Tuto platnost posoudí zvolené `--layout` při převodu
příkazem `template`.

Souřadnice používají `row` a `column`, počítají se od 1 a jejich počátek leží v levém horním rohu. Řádky rostou směrem dolů a sloupce doprava. Slova se mohou křížit pouze tehdy, mají-li na společné souřadnici stejné písmeno.

### Tajenky

Volitelný seznam `secrets` uchovává jednu nebo více tajenek. Povinné `type` rozlišuje tajenku určenou poli, souvislým slovem nebo několika bloky.

Každá položka `secrets` může mít jedno volitelné zadání `prompt`:

```yaml
secrets:
  - type: word
    answer: ZELENÍ
    start: {row: 1, column: 1}
    direction: horizontal
    prompt:
      text: 'Lidové rčení: „Komu se nelení, tomu se …“'
      placement: above
      alignment: left
```

`prompt.text` je text pro luštitele mimo mřížku. Volitelné `placement` (`above` nebo `below`) a `alignment` (`left` nebo `right`) mají stejný význam jako v cílovém `secret_prompts`; výchozí je umístění nahoře a zarovnání doleva. Zadání patří celé tajence, takže u `type: parts` se uvádí vedle `parts`, nikoli u jednotlivých částí. Jde o jiný údaj než `legend`: tajenkové slovo může mít současně legendu uvnitř mřížky nebo pod ní i zadání celé tajenky nad či pod mřížkou.

Tajenka `type: cells` obsahuje neprázdný seznam `cells`:

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
```

Souřadnice se nesmějí v jednom seznamu opakovat, musí ležet uvnitř mřížky a odkazovat na písmena některého umístěného běžného nebo tajenkového slova. Tato podoba tajenky nemá vlastní legendu.

Výchozí `arrows: false` dovoluje libovolné rozmístění samostatných polí bez ohledu na jejich sousedství. Pořadí položek `cells` v tomto případě nemá význam: model tajenku čte po řádcích shora dolů a v každém řádku zleva doprava. [Příklad s rozptýlenými poli](../examples/specification-scattered-secret.yaml) zapisuje souřadnice záměrně v jiném pořadí, ale vytvoří text `TAJENKA`.

Při `arrows: true` naopak pořadí položek určuje cestu. Tajenka musí obsahovat alespoň dvě pole a každá dvě po sobě jdoucí pole musí sdílet hranu. Převod do cílové mřížky vloží `arrow` do prvního pole a potom do každého pole, z něhož cesta pokračuje jiným směrem než předchozí krok. Vykreslený zobáček vždy ukazuje k následujícímu poli; koncové pole jej nemá.

Tajenka `type: word` je souvislé vodorovné nebo svislé slovo:

```yaml
secrets:
  - type: word
    answer: KŘÍŽOVKÁŘ
    start: {row: 5, column: 2}
    direction: horizontal
```

Položky `answer`, `start` a `direction` mají stejný význam jako u běžného umístěného slova. Odpověď zadává autor přímo a nekontroluje se proti slovníku; musí pouze používat podporovaná velká písmena a české `CH` opět zabírá jediné pole. Tajenkové slovo se neopakuje ve `words`; samo obsazuje písmenná pole a může se křížit s ostatními slovy.

Vynechaná `legend` se při načtení doplní přesným textem `Tajenka`. Při převodu do cílové mřížky tak slovo dostane legendovou buňku označenou „Tajenka“ a písmena v buňkách `type: secret`. Výslovná neprázdná `legend` zůstává podporovaná kvůli zpětné kompatibilitě.

#### Vícedílná tajenka

Tajenka `type: parts` obsahuje alespoň dvě části v poli `parts`. Pořadí částí určuje pořadí, ve kterém se jejich obsah spojí do výsledné tajenky:

```yaml
secrets:
  - type: parts
    parts:
      - type: word
        answer: DÁREK
        start: {row: 5, column: 1}
        direction: horizontal
      - type: word
        answer: RADOST
        start: {row: 6, column: 1}
        direction: horizontal
      - type: word
        answer: ÚSMĚV
        start: {row: 7, column: 1}
        direction: horizontal
        legend: 3. díl tajenky
```

Každá část je `type: cells` nebo `type: word`. Část z buněk bez zobáčků smí obsahovat libovolně rozmístěná pole a čte se po řádcích; její `arrows: true` místo toho určí vlastní souvislou cestu, nezávisle na ostatních částech. Jednopísmenná část nemůže mít zobáček, protože nemá následující pole.

Slovní část bez `legend` dostane podle své pozice automatický popisek `1. část tajenky`, `2. část tajenky` a tak dále. Výslovná neprázdná legenda může použít jinou rovnocennou formulaci, například `2. díl tajenky` nebo `Tajenka: 4. díl`. Číslo se odvozuje od pozice mezi všemi částmi, takže smíšená tajenka může mít například první část bez legendy a druhou část označenou `2. část tajenky`.

Všechny varianty mohou být v jednom zadání. Cílový dokument `grid` je při vykreslení zobrazuje stejným zvýrazněním; jejich původní definici zachovává pouze `specification`.

### Umístění pomůcky

Obsah pomocné buňky tvoří odpovědi s `in_help: true` v pořadí, v jaké
jsou uvedené ve `words`. Není-li poloha pomůcky zadaná, převod na šablonu ji
po rozložení slov, legend a ostatních buněk vloží do první volné buňky.
Buňky prochází po řádcích zleva doprava a shora dolů.

Vlastní polohu lze určit takto:

```yaml
help:
  position: {row: 1, column: 7}
```

Blok `help` je platný jen tehdy, když má alespoň jedno slovo `in_help: true`. Výslovná souřadnice musí ležet uvnitř mřížky a nesmí být obsazená písmenem. Úplnou kontrolu proti buňkám vzniklým při generování provede generátor.

Loader již ověřuje rozměry, rozsah běžných i tajenkových slov, shodu
písmen na kříženích, obsazenost vybraných tajenkových polí a základní platnost
výslovné polohy pomůcky. Převod `specification → crossword` navíc odmítne
překryv dvou slotů ve stejném směru, kolizi legendy a písmene nebo pomůcky a
jiné buňky. Příkazy `latex` a `render` přijímají `grid` nebo `crossword`;
zadání lze převést rourou `template ZADÁNÍ.yaml | latex -` nebo rovnou
sestavit jako PDF pomocí `template ZADÁNÍ.yaml | render -`.

## Validace

Strojová pravidla jsou v samostatných schématech pro
[cílovou mřížku](../src/krizovkar/schemas/grid-v1.schema.json),
[editovatelnou křížovku](../src/krizovkar/schemas/crossword-v1.schema.json) a
[zadání](../src/krizovkar/schemas/specification-v1.schema.json). Schémata
odmítají neznámé a chybně napsané položky i nulové, záporné nebo neceločíselné
rozměry. Pythonové loadery navíc kontrolují vztahy, které závisejí na více
částech dokumentu.

Validace cílové mřížky rozlišuje dvě závažnosti:

- `error` označuje chybu datového modelu, kvůli které dokument nelze bezpečně načíst nebo dále zpracovat,
- `warning` označuje formálně platnou mřížku, která může být hůře čitelná nebo nesplňuje zvolená pravidla kvality.

Příkaz `krizovkar validate` při chybě vrací kód `2`. Samotná varování vypíše, ale vrací kód `0`, takže neblokují vykreslení ani další zpracování. Každá položka reportu obsahuje závažnost, strojově čitelný kód, cestu k místu v dokumentu a českou zprávu.

Současná kvalitativní kontrola neurčuje jeden druh celé mřížky. Každý nový vodorovný či svislý běh písmen musí mít vlastní zdroj legendy: bezprostředně předcházející buňku `type: legend`, nebo `number` v počátečním písmenném poli. Za nový běh se považuje také heslo za silným předělem. Vepsaná jednoduchá legenda má jeden text a navazující směr, dvojitá dva texty v pořadí doprava a dolů; tato pravidla se kontrolují i vedle číselných legend v témže dokumentu. Tajenkové rohové šipky jsou samostatná pomůcka pro pořadí čtení a varování pro směrové šipky legend nevyvolávají. Všechny běžné a tajenkové písmenné buňky zároveň musí tvořit jedinou oblast propojenou společnými hranami; legendy, pomůcky a nevyplňované buňky jsou její hranice. Jde o neblokující formální pravidla pro dobrý výsledek, nikoli o další omezení datového formátu.

Chybí-li některé písmenné `value` nebo legendové `texts`, validátor přidá
jediné neblokující varování `grid.unfinished`. Nevyplněná mřížka tak zůstává
platná a vykreslitelná; kontrola pouze odliší pracovní či tiskovou podobu od
zcela doplněného výsledku.

Minimální dokumenty jsou v příkladech [cílové mřížky](../examples/grid-minimal.yaml) a [zadání](../examples/specification-minimal.yaml).

Převod nevyplněné šablony ukazuje [nevyplněná cílová mřížka](../examples/grid-unfilled.yaml).

Doplněné sloty a pomůcku ukazuje
[šablona ze zadání](../examples/template-from-specification.yaml).

Vyšší zadání ukazuje [příklad s umístěnými slovy a automatickou pomůckou](../examples/specification-placed-words.yaml).

Oba způsoby určení tajenky ukazuje [příklad s vybranými poli a tajenkovým slovem](../examples/specification-secrets.yaml).

Text lidového rčení a odpověď `ZELENÍ` ukazuje [zadání tajenky s textem](../examples/specification-secret-prompt.yaml) a odpovídající [cílová mřížka](../examples/grid-secret-prompt.yaml).

Nespojitá pole čtená po řádcích ukazuje [příklad s rozptýlenou tajenkou](../examples/specification-scattered-secret.yaml).

Více bloků bez legend i s legendami ukazuje [příklad vícedílných tajenek](../examples/specification-multipart-secrets.yaml).

Čísla, silné mezislovní předěly a vnější legendy ukazuje [příklad s číselnými legendami](../examples/grid-classic.yaml).

Současné použití vepsaných a číselných legend ukazuje [příklad se smíšenými legendami](../examples/grid-mixed-clues.yaml).

Vyplněná cílová mřížka je v [příkladu s náhodnými písmeny](../examples/grid-random-letters.yaml).

Smíšené typy buněk ukazuje [příklad s tajenkou](../examples/grid-secret.yaml).

Začátek a dva body obratu ukazuje [příklad tajenkové cesty se zobáčky](../examples/grid-secret-arrows.yaml).

Česká písmena s diakritikou a jednopísmenné `CH` ukazuje [mřížka s českými písmeny](../examples/grid-czech-letters.yaml).

Jednoduchou i dvojitou legendu ukazuje [příklad s legendami](../examples/grid-legend.yaml).

Nevyplňované buňky ukazuje [příklad s diagonálními křížky](../examples/grid-empty.yaml).

Pomocnou buňku ukazuje [příklad se seznamem slov](../examples/grid-help.yaml).

## Rozvoj formátu

- Nová data se mají přidávat pod srozumitelně pojmenované položky, nikoli odvozovat z pořadí zápisu v YAML.
- Zpětně kompatibilní rozšíření mohou zůstat ve verzi `1`; nekompatibilní změna vyžaduje novou hlavní verzi.
- Příklady, dokumentace a příslušné schéma se při změně modelu aktualizují společně.
