# Křížovkář

Křížovkář je připravovaný otevřený nástroj pro tvorbu švédských, klasických a dalších druhů křížovek.

## Stav projektu

Repozitář je v úvodní fázi. Obsahuje první verzi datového modelu,
experimentální generátory švédské a číslované mřížky z JSON slovníku,
automatický převod umístěného zadání na šablonu, převod výsledku do
upravitelné LaTeXové sazební šablony, její překlad do PDF a grafické
rozhraní se samostatnými okny YAML šablon a křížovek z vlastních hesel.
Další rozšíření editoru budou postupně zpřístupňovat například tajenky a
automatické plnění.

## Grafické rozhraní

Grafické rozhraní se spustí samostatným příkazem:

```shell
uv run krizovkar-gui
```

Po spuštění se otevře nový neuložený dokument šablony. Každé viditelné
okno představuje právě jeden YAML soubor a v titulku ukazuje jeho název,
případně **Nová šablona** nebo **Nová křížovka**. Hvězdička před
názvem označuje neuložené změny.

Podle kořenového klíče `kind` má okno jednu ze dvou podob:

- **Šablona** určuje rozměr, švédskou nebo číslovanou podobu a všechna místa
  pro vodorovná a svislá hesla. Má vlastní náhled, formát stránky a uložení
  do YAML nebo tiskového PDF. Tlačítko **Vytvořit křížovku podle této
  šablony** otevře nové okno s nezávislým dokumentem `kind: crossword`.
- **Křížovka** drží vlastní kopii zvolené šablony a doplněná hesla. Místo se
  vybírá kliknutím v náhledu nebo v seznamu; formulář ukazuje jeho délku a
  písmena známá z křížení. Dokument lze průběžně ukládat do YAML a po
  vyplnění všech míst také jako tiskovou křížovku a samostatné řešení v PDF.

Nabídka **Soubor** umí otevřít existující `kind: template` nebo
`kind: crossword` v dalším okně. `Ctrl+N` otevře novou šablonu, `Ctrl+O`
vybere existující dokument, `Ctrl+S` uloží aktuální soubor a
`Ctrl+Shift+S` zvolí novou cestu. `Ctrl+W` zavře pouze dané okno; pokud
obsahuje neuložené změny, editor se zeptá na jejich uložení. Otevřená
šablona a křížovka jsou po vytvoření nezávislé; změna jednoho okna proto
obsah druhého neovlivní.

Ve švédské podobě jsou místa pro nápovědy součástí předem vytvořené mřížky.
Číslovaná podoba ponechá všechna pole pro písmena a nápovědy vysází pod
mřížkou. Ruční zadávání souřadnic ani směru proto není potřeba. Nesprávnou
délku, opakované heslo nebo rozporné písmeno aplikace odmítne konkrétní
zprávou. Editor zatím nezadává tajenky, vlastní pomůcku ani automatické
vyplnění ze slovníku.

Přímé uložení PDF používá LuaLaTeX a vyžaduje stejnou instalaci TeX Live
jako příkaz `render`.

GUI vyžaduje Python s podporou Tk 8.6 nebo novější. Modul `tkinter` je součástí
standardní knihovny Pythonu, některé systémové distribuce jej ale instalují jako
samostatný balíček.

## Zaměření

Projekt má postupně nabídnout zejména:

- tvorbu švédských křížovek s legendami přímo v mřížce,
- tvorbu klasických a dalších typů křížovek,
- otevřený datový formát oddělený od uživatelského rozhraní,
- kontrolu mřížky, výrazů a křížení,
- export pro tisk i digitální použití.

Experimentální generátor ověřuje základní práci se slovníkem a křížením; konkrétní rozsah první funkční verze bude popsán v roadmapě.

## Datový model

Křížovkář rozlišuje čtyři samostatné druhy YAML dokumentů:

- `kind: specification` je vstupní zadání se slovy, nápovědami, tajenkami a pravidly skládání,
- `kind: template` je nevyplněná šablona s rolemi buněk a sloty hesel,
- `kind: crossword` je editovatelná křížovka s vlastní kopií šablony
  a postupně doplňovanými hesly,
- `kind: grid` je mřížka s konkrétními rolemi buněk a volitelně již doplněnými
  písmeny a legendami, kterou lze přímo vykreslit.

```text
umístěné specification + volba rozvržení → template
template → crossword (ruční doplňování) → grid → LaTeX → PDF
template → grid (pevný nebo nevyplněný obsah) → LaTeX → PDF
template + slovník → fill → grid → LaTeX → PDF
požadavky + slovník → generate (= template + fill) → grid
```

YAML dokument `kind: template` je datová šablona určená k plnění hesly.
Následná LaTeXová sazební šablona je samostatný textový výstup určený
k vizuálním úpravám a překladu do PDF.

Dokument `kind: crossword` používá stejné role buněk a sloty, ale
jednoznačně označuje samostatnou rozpracovanou nebo hotovou křížovku.
Může proto obsahovat libovolný počet doplněných hesel a po opětovném
otevření se nezamění se zdrojovou šablonou. Zápis ukazuje
[minimální křížovka](examples/crossword-minimal.yaml).

Nejmenší platná cílová mřížka zatím určuje pouze rozměr:

```yaml
format: krizovkar
kind: grid
version: 1
grid:
  width: 15
  height: 10
```

Šablona každému heslu určuje stabilní identifikátor, začátek, směr a
délku; matice buněk rozlišuje budoucí písmena, vepsané legendy, pomůcku a
nevyplňovaná pole. Hustá šablona nechá odpovědi a texty legend neznámé,
šablona převedená ze zadání je naopak uchová jako pevný obsah slotů.
Minimální zápis ukazuje [příklad šablony](examples/template-minimal.yaml) a
pevnou variantu [šablona ze zadání](examples/template-from-specification.yaml).

Šablona může navíc rezervovat jeden nebo více slotů pro části tajenky. Známá tajenka se ukládá jako seznam slov bez mezer a interpunkce, aby se neztratila povolená místa budoucího rozdělení. `word_count` u každé části určuje, kolik po sobě jdoucích slov se spojí do příslušného slotu. Ukazuje to [šablona s tajenkou](examples/template-secret.yaml). Pokud konkrétní znění zatím není známé, `words` i `word_count` se vynechají a zůstanou jen připravené sloty.

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

U `type: cells` musí každé vybrané pole obsahovat písmeno. Bez šipek mohou být pole samostatná a libovolně rozmístěná; tajenka se z nich čte automaticky po řádcích zleva doprava a shora dolů, bez ohledu na pořadí souřadnic v YAML. Ukazuje to [zadání s rozptýlenou tajenkou](examples/specification-scattered-secret.yaml). Volitelné `arrows: true` naopak používá zadané pořadí jako cestu přes sousední pole a na její začátek i každé místo změny směru přidá plný černý zobáček. Základnou sedí na hraně pole a špičkou ukazuje dovnitř pokračující tajenky. `type: word` se umisťuje a kříží stejně jako běžné heslo, ale jeho písmena budou zvýrazněná jako tajenka. Odpověď zadává autor přímo a nemusí být ve slovníku; vynechaná `legend` dostane automaticky text `Tajenka`. Obě souvislé podoby ukazuje [zadání s tajenkami](examples/specification-secrets.yaml).

Každá tajenka může mít vlastní zadání `prompt`, které je nezávislé na vepsané nebo číselné `legend`:

```yaml
prompt:
  text: 'Lidové rčení: „Komu se nelení, tomu se …“'
  placement: above
  alignment: left
```

`placement` vybírá umístění `above` nebo `below` a `alignment` zarovná text `left` nebo `right`; při vynechání se použije `above` a `left`. U `type: parts` patří zadání celé složené tajence. Ucelený zápis odpovědi `ZELENÍ` ukazuje [zadání tajenky s textem](examples/specification-secret-prompt.yaml).

Jedna tajenka může mít také několik částí v určeném pořadí:

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
```

Slovní části bez výslovné `legend` dostanou postupně popisky `1. část tajenky`, `2. část tajenky` a tak dále. Vlastní text může použít také formulaci `2. díl tajenky` nebo `Tajenka: 3. díl`. Části `type: cells` vlastní legendu nemají, mohou obsahovat samostatná pole a každá může samostatně zapnout zobáčky pro souvislou cestu. Obě vícedílné podoby ukazuje [zadání s vícedílnými tajenkami](examples/specification-multipart-secrets.yaml).

Význam dokumentů popisuje [specifikace datového modelu](docs/datovy-model.md). Strojová pravidla jsou oddělená v [JSON Schema zadání](src/krizovkar/schemas/specification-v1.schema.json), [JSON Schema šablony](src/krizovkar/schemas/template-v1.schema.json), [JSON Schema editovatelné křížovky](src/krizovkar/schemas/crossword-v1.schema.json) a [JSON Schema cílové mřížky](src/krizovkar/schemas/grid-v1.schema.json).

Model nemá přepínač mezi švédskou a čárkovanou křížovkou. Zadání hesla, jeho odpovědi a legendy je v obou případech stejné; konkrétní cílová mřížka pouze určí, zda legendu vloží do samostatné buňky, nebo ji spojí s číslem písmenné buňky a uvede pod mřížkou. Legendová buňka zabírá místo, takže stejné zadání může být platné pro jedno rozložení a nevejít se do jiného. Oba způsoby lze v jedné mřížce libovolně kombinovat.

Mřížka může obsahovat řádky explicitně typovaných buněk:

```yaml
grid:
  width: 3
  height: 1
  cells:
    - [{type: secret, value: Č, arrow: right}, {type: letter, value: CH}, {type: letter, value: Á}]
```

Typ `letter` označuje běžné písmenné pole a `secret` pole patřící do tajenky.
Jejich `value` lze do doplnění odpovědi vynechat. Známé české `CH` zabírá jednu
buňku stejně jako samostatné písmeno a písmena si zachovávají diakritiku.
Tajenková buňka má v PDF světle šedé pozadí a může mít jeden směrový zobáček
`arrow` ve směru `up`, `right`, `down` nebo `left`. Jde o jinou značku než
seznam `arrows` v legendové buňce. Cílová mřížka už nerozlišuje, zda tajenku
určil seznam polí, nebo souvislé heslo. Zápis ukazuje [nevyplněná mřížka](examples/grid-unfilled.yaml),
[mřížka s českými písmeny](examples/grid-czech-letters.yaml) a
[ukázková cesta se zobáčky](examples/grid-secret-arrows.yaml).

Cílový dokument ukládá texty k tajenkám v kořenovém seznamu `secret_prompts`. Každá položka má stejné `text`, `placement` a `alignment` jako `prompt` ve vstupním zadání; seznam dovoluje v jedné mřížce více tajenek. Renderer je sází nad nebo pod mřížku a zarovnává k její levé nebo pravé hraně. Spodní zadání se zobrazí mezi mřížkou a případnými číselnými legendami. Zápis ukazuje [cílová mřížka se zadáním tajenky](examples/grid-secret-prompt.yaml).

Čárkované rozložení může písmenné buňce přidat počáteční `number` a silné mezislovní `bars` na její pravé či dolní hraně. Renderer vloží číslo do levého horního rohu, předěly vykreslí stejným silným tahem jako vnější rám a očíslované `clues` rozdělí pod mřížkou do sloupců „Vodorovně“ a „Svisle“. Číslo bez odpovídající legendy může označit například tajenku bez nápovědy. Tyto položky nijak nevylučují buňky `type: legend`: [smíšená mřížka](examples/grid-mixed-clues.yaml) používá vepsané i číselné legendy současně, zatímco [číslovaná mřížka](examples/grid-classic.yaml) ukazuje samotné vnější legendy.

Vyplněná legenda používá neprázdný seznam textů a může u nich výslovně uvést
směrové šipky. V nevyplněné mřížce lze `texts` vynechat nebo pomocí `null`
zachovat počet prázdných částí složené legendy:

```yaml
{type: legend}
{type: legend, texts: [null, null]}
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

## Vstup a výstup příkazů

Volba `-o` neboli `--output` je u příkazů `template`, `grid`, `fill`,
`generate`, `latex` a `render` nepovinná. Bez ní příkaz zapíše výsledný
YAML, textový LaTeX nebo binární PDF na standardní výstup, takže jej lze
přesměrovat nebo předat dalšímu programu:

```shell
uv run krizovkar template examples/specification-placed-words.yaml \
  --layout swedish > build/placed-template.yaml
uv run krizovkar template --width 15 --height 10 > build/template.yaml
uv run krizovkar grid build/template.yaml > build/unfilled-grid.yaml
uv run krizovkar generate slovnik.json > build/grid.yaml
uv run krizovkar latex build/grid.yaml > build/grid.tex
uv run krizovkar render build/grid.yaml > build/grid.pdf
```

Stavová hláška jde v tomto režimu na standardní chybový výstup a výsledná data neznečistí. Při zadaném `--output` se dál zapisuje atomicky do souboru, existující soubor se bez `--force` nepřepíše a stavová hláška se vypíše na standardní výstup.

Místo vstupního souboru přijímají příkazy `template`, `grid`, `fill`,
`generate`, `validate`, `latex` a `render` také `-`, které znamená standardní
vstup. U `template` jde o vstupní zadání. U příkazu `fill` lze tímto
způsobem načíst šablonu nebo slovník, ale ne oba vstupy současně. Výstupy
lze díky tomu spojovat přímo rourou. Datová šablona se může převést na
LaTeX bez mezikroku:

```shell
uv run krizovkar template --width 15 --height 10 \
  | uv run krizovkar latex - > build/template.tex
```

Nebo z ní lze rovnou sestavit PDF; `render` uvnitř vytvoří stejný LaTeXový
zdroj a přeloží jej LuaLaTeXem:

```shell
uv run krizovkar template --width 15 --height 10 \
  | uv run krizovkar render - > build/template.pdf
```

Nebo lze v rouře zachovat i samostatný převod na cílovou mřížku:

```shell
uv run krizovkar template --width 15 --height 10 \
  | uv run krizovkar grid - \
  | uv run krizovkar render - > build/unfilled-grid.pdf
```

## Vytvoření šablony

Umístěné zadání převede na šablonu jeho volitelný poziční argument:

```shell
uv run krizovkar template examples/specification-placed-words.yaml \
  --layout swedish \
  --output build/template-from-specification.yaml
```

Převod zachová rozměr, odpovědi, legendy, tajenky, jejich zadání i pomůcku.
Každé umístěné běžné nebo tajenkové slovo se stane pevným slotem.
`--layout swedish` rezervuje volnou buňku bezprostředně vlevo od vodorovného
hesla nebo nad svislým heslem. Pokud tam není místo nebo by legenda překryla
písmeno, převod skončí s konkrétní chybou. `--layout numbered` samostatné
legendové buňky nepotřebuje a texty připraví jako vnější číslované legendy.

Rozměr i tajenky už v tomto režimu určuje zadání. Volby `--width`,
`--height`, `--seed` a volby tajenky proto nelze se vstupním souborem
kombinovat.

Bez vstupního zadání vytvoří stejný příkaz hustou šablonu bez slovníku a
bez znalosti budoucích odpovědí. Výchozí rozvržení je švédské:

```shell
uv run krizovkar template \
  --width 15 \
  --height 10 \
  --output build/template.yaml
```

Číslovanou (čárkovanou) šablonu zvolí `--layout numbered`:

```shell
uv run krizovkar template \
  --layout numbered \
  --width 15 \
  --height 10 \
  --output build/numbered-template.yaml
```

Stejné rozvržení a rozměry vytvoří stejnou šablonu. Švédský generátor rozdělí plochu na písmenné obdélníky, legendové buňky a jejich nevyplňované průsečíky. Číslovaná varianta ponechá všechny buňky písmenné, obě osy rozdělí silnými předěly a budoucí legendy umístí vně mřížky. Obě rozvržení používají délky hesel 3 až 8 a každému vodorovnému i svislému heslu přidělí vlastní slot. Příkaz existující soubor nepřepíše bez volby `--force`.

Tajenku lze při tvorbě šablony zadat čtyřmi způsoby:

```shell
# Pouze celková délka
uv run krizovkar template --width 7 --height 6 \
  --secret-length 6 --output build/secret-length.yaml

# Předem určené délky částí
uv run krizovkar template --width 7 --height 12 \
  --secret-parts 5,6 --output build/secret-lengths.yaml

# Konkrétní tajenka s automatickým dělením na švech slov
uv run krizovkar template --width 7 --height 12 \
  --secret "DÁREK RADOST" --output build/secret-auto.yaml

# Konkrétní a pevně rozdělená tajenka
uv run krizovkar template --width 7 --height 12 \
  --secret-part DÁREK --secret-part RADOST \
  --output build/secret-fixed.yaml
```

Tyto volby fungují pro obě hodnoty `--layout`. U konkrétního textu se velikost písmen sjednotí, mezery a interpunkce se do buněk nezapisují a seznam slov zachová všechny povolené švy. Automatické dělení nikdy nerozdělí slovo. Generátor podle potřeby změní jinak vyvážené délky běžných slotů tak, aby maska obsahovala požadované délky tajenky od 3 do 8 polí; pokud se požadavek do zadaného rozměru nevejde, skončí s chybou. Volitelné `--secret-prompt` doplní zadání; jeho pozici a zarovnání určují `--secret-prompt-placement` a `--secret-prompt-alignment`. Seed ovlivňuje výběr vhodných slotů.

Platnou šablonu lze bez slovníku převést na cílovou mřížku:

```shell
uv run krizovkar grid build/template.yaml \
  --output build/unfilled-grid.yaml
```

Převod zachová nevyplňovaná, legendová a pomocná pole, čísla a silné
předěly číslovaného rozvržení, zvýraznění tajenek, jejich zobáčky a zadání.
U husté šablony zůstanou písmena a texty legend prázdné. Šablona vytvořená
ze zadání naopak přenese své pevné odpovědi, legendy a slova pomůcky.
Šablonu lze bez mezikroku převést na sazební šablonu příkazem
`krizovkar latex build/template.yaml` nebo z ní rovnou sestavit PDF příkazem
`krizovkar render build/template.yaml`.

Šablonu lze později vyplnit samostatně:

```shell
uv run krizovkar fill build/template.yaml slovnik.json \
  --seed 10 \
  --output build/filled-grid.yaml
```

Plnění funguje i pro ručně vytvořené a částečně pevné šablony. Pevné
sloty zachová; pro každý zbývající slot vybere heslo odpovídající délky,
zachová shodná písmena na kříženích a stejnou odpověď nepoužije dvakrát.
Slot s vepsanou legendovou buňkou vytvoří švédskou legendu; slot bez ní
dostane číslo a vnější legendu. Stejná šablona, slovník a seed vytvoří
stejnou cílovou mřížku.

Známou tajenku uloženou v šabloně `fill` doplní automaticky a její sloty nevyhledává ve slovníku. Rezervuje-li šablona jen prázdné tajenkové sloty, předá se konkrétní text pomocí `--secret` nebo opakovaného `--secret-part`. Stejné volby lze použít i u šablony bez rezervace; plnění pak vhodné sloty tajenky samo vybere. Tajenková pole se ve výsledné mřížce zvýrazní a jednotlivé části dostanou legendy `1. část tajenky`, `2. část tajenky` a tak dále.

## Pokusné generování

Generátor přijímá slovník jako JSON objekt. Klíčem je heslo složené z podporovaných velkých písmen včetně diakritiky a hodnotou neprázdný seznam možných legend v preferovaném pořadí:

```json
{
  "OCHOČENÁ": ["Zkrocená"],
  "ŘEKA": ["Vodní tok"]
}
```

Vyplněnou mřížku lze vytvořit jedním příkazem a následně vykreslit:

```shell
uv run krizovkar generate slovnik.json \
  --width 15 \
  --height 10 \
  --seed 10 \
  --output build/generated-grid.yaml
uv run krizovkar render build/generated-grid.yaml \
  --output build/generated-grid.pdf
```

Bez volby `--layout` vznikne švédská mřížka. Číslovanou mřížku s vnějšími legendami vytvoří:

```shell
uv run krizovkar generate slovnik.json \
  --layout numbered \
  --width 15 \
  --height 10 \
  --seed 10 \
  --output build/generated-numbered-grid.yaml
```

`generate` skládá pro obě rozvržení stejné operace jako samostatné `template` a `fill`. Konkrétní tajenku může vložit rovnou; samotná délka bez odpovědi je určená jen pro uložení šablony:

```shell
uv run krizovkar generate slovnik.json \
  --width 15 \
  --height 10 \
  --secret ZELENÍ \
  --secret-prompt 'Lidové rčení: „Komu se nelení, tomu se …“' \
  --output build/generated-secret-grid.yaml
```

Automatické dělení víceslovné tajenky používá `--secret`; pevné rozdělení vznikne opakováním `--secret-part`.

Stejný slovník, rozvržení, rozměr a seed vytvoří stejnou mřížku. Výchozí švédský generátor rozdělí plochu legendovými řádky a sloupci na písmenné obdélníky; prázdné zůstávají pouze průsečíky legendových os. Číslovaný generátor použije celou plochu pro písmena, začátky hesel očísluje po řádcích a jejich texty zapíše jako vnější legendy. Další hesla v témže řádku nebo sloupci oddělí silným předělem. V obou případech patří každá písmenná buňka jednomu vodorovnému i jednomu svislému výrazu.

Pokud švédská maska obsahuje více písmenných obdélníků oddělených legendovými osami, jejich hesla se navzájem nekříží. Kvalitativní validace proto upozorní, že výsledná slova tvoří oddělené ostrovy; číslovaná varianta má naproti tomu souvislou písmennou plochu.

Ve švédské variantě legendy pokrývají horní a levou stranu každého písmenného bloku. Na horním okraji chybí legenda jen ve sloupci s dalšími vnitřními legendami a na levém okraji jen v řádku s dalšími vnitřními legendami. Každá vepsaná legenda má jediný text a právě jeden možný směr navazujícího hesla, takže nepotřebuje šipku. První experimentální verze zatím nevytváří pomůcku a nehodnotí jazykovou kvalitu hesel. Zdrojový slovník není součástí projektu; uživatel musí mít právo jeho obsah použít.

## Validace

Datový formát a pravidla dobré křížovky jsou dvě oddělené vrstvy. Příkaz `validate` nejprve ověří, zda lze YAML bezpečně načíst jako cílovou mřížku, a potom posoudí společná pravidla jejího rozložení:

```shell
uv run krizovkar validate build/generated-grid.yaml
```

Chyba znamená neplatný nebo vnitřně rozporný datový model a příkaz skončí návratovým kódem `2`. Varování znamená platnou mřížku, kterou lze dál zpracovat a vykreslit, ale porušuje některé pravidlo kvality; návratový kód zůstává `0`.

Validátor nepřiřazuje celé mřížce jeden druh. U každého začátku hesla samostatně přijme bezprostředně předcházející legendovou buňku nebo číslo; silný předěl přitom zakládá nové heslo. Proto kontroluje vepsané legendy i ve mřížce, která zároveň obsahuje `number`, `bars` nebo vnější `clues`. Dále varuje zejména před směrovými šipkami vepsaných legend, nesouladem počtu jejich textů a navazujících směrů a oddělenými písmennými ostrovy. Zobáčky tajenky tato varování nevyvolávají.

## Vytvoření LaTeXu a PDF

Projekt vyžaduje Python 3.11 nebo novější. Pythonové závislosti lze
nainstalovat pomocí [uv](https://docs.astral.sh/uv/):

```shell
uv sync
```

Příkaz `latex` převede ukázkový YAML na samostatnou textovou sazební šablonu:

```shell
uv run krizovkar latex examples/grid-random-letters.yaml \
  --page-format A4 \
  --output build/random-letters.tex
```

Výsledný soubor používá TikZ, zachovává vektorovou mřížku a lze jej před
překladem ručně upravit. K samostatnému překladu je potřeba LuaLaTeX, například
z distribuce TeX Live, a balíčky `fontspec`, `babel`, `tikz`, `adjustbox` a
`geometry`:

```shell
lualatex -interaction=nonstopmode -halt-on-error -no-shell-escape \
  -output-directory=build build/random-letters.tex
```

Stejné dva kroky provede najednou příkaz `render`. LaTeXovou šablonu vytvoří
v dočasném adresáři a PDF sestaví výhradně jejím překladem pomocí příkazu
`lualatex`:

```shell
uv run krizovkar render examples/grid-random-letters.yaml \
  --page-format A4 \
  --output build/random-letters.pdf
```

Vstupem `latex` i `render` může být cílová mřížka `kind: grid`,
šablona `kind: template` i editovatelná křížovka `kind: crossword`; oba
strukturální dokumenty se automaticky převedou na mřížku bez slovníku.
Volba `--page-format` přijímá `A0` až `A6`, `Letter` a `Legal`,
nerozlišuje velikost písmen a její výchozí hodnota je `A4`. Obsah se podle
potřeby zmenší tak, aby zůstal na jedné stránce zvoleného formátu.

U vyplněné cílové mřížky LaTeX i PDF standardně zobrazí písmena. Pro jejich
skrytí přidej k příkazu `latex` nebo `render` volbu `--blank`; datová šablona a
nevyplněná mřížka zůstanou prázdné i bez této volby:

```shell
uv run krizovkar render examples/grid-secret-arrows.yaml \
  --blank \
  --output build/secret-arrows-blank.pdf
```

Prázdná varianta skryje hodnoty běžných i tajenkových písmenných buněk. Zadání tajenek nad či pod mřížkou, legendy uvnitř i pod mřížkou, čísla, pomůcky, nevyplňovaná pole, šedé zvýraznění tajenky a její zobáčky zůstanou zobrazené stejně jako ve vyplněné variantě.

Bez volby `--output` zapíše `latex` textový zdroj a `render` binární PDF na
standardní výstup. Pro uložení pomocí přesměrování lze použít například
`uv run krizovkar latex mřížka.yaml > mřížka.tex` nebo
`uv run krizovkar render mřížka.yaml > mřížka.pdf`. Při výslovném
`--output` příkazy existující soubor nepřepíší, dokud není přidána volba
`--force`. Chybějící LuaLaTeX nebo chyba jeho překladu ukončí `render` s
konkrétní chybovou zprávou; samotný export příkazem `latex` jej nevyžaduje.

Nápovědu vypíše:

```shell
uv run krizovkar --help
```

Uživatelské rozhraní je české, včetně nápovědy, stavových a chybových hlášek.
Anglicky zůstávají názvy příkazů, voleb, povolených hodnot a klíčů datového
formátu, například `latex`, `render`, `--output`, `numbered` nebo `grid`.

Testy se spouštějí příkazem:

```shell
uv run python -m unittest discover -s tests
```

## Vývoj

Pravidla spolupráce jsou v [CONTRIBUTING.md](CONTRIBUTING.md). Každá dokončená logická změna se po kontrole samostatně commitne a ihned odešle na GitHub.

## Licence

Obsah repozitáře je uvolněn pod [CC0 1.0 Universal](LICENSE). Autoři se v maximálním rozsahu dovoleném právem vzdávají autorských a souvisejících práv.
