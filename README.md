# Křížovkář

Křížovkář je připravovaný otevřený nástroj pro tvorbu švédských, klasických a dalších druhů křížovek.

## Stav projektu

Repozitář je v úvodní fázi. Obsahuje první verzi datového modelu,
experimentální plnění švédské a číslované křížovky z JSON slovníku,
automatický převod umístěného zadání na šablonu křížovky, převod
výsledku do upravitelného LaTeXového dokumentu, jeho překlad do PDF a grafické
rozhraní se samostatnými okny YAML křížovek z vlastních hesel, které lze
uložit v libovolném stavu a znovu používat jako šablony.
Další rozšíření editoru budou postupně zpřístupňovat například tajenky a
automatické plnění.

## Grafické rozhraní

Grafické rozhraní bez existujícího souboru se spustí samostatným
příkazem:

```shell
uv run krizovkar-gui
```

Tím se otevře systémový dialog pro výběr existující křížovky. Po jeho
zavření zůstane aplikace spuštěná bez otevřeného dokumentu; z nabídky
**Soubor** lze vygenerovat novou šablonu, otevřít soubor nebo vybrat některý z
posledních dokumentů. Existující soubor
lze také otevřít přímo při spuštění; každá zadaná cesta dostane vlastní
okno a systémový dialog se v tom případě nezobrazí:

```shell
uv run krizovkar-gui examples/template-unfilled.yaml \
  examples/crossword-minimal.yaml
```

Každé viditelné okno představuje právě jeden YAML soubor a v titulku ukazuje
jeho název, případně **Nová šablona**. Hvězdička
před názvem označuje neuložené změny. Na macOS má otevřený nebo uložený
dokument v záhlaví také systémovou ikonu svého YAML souboru, kterou lze
přetáhnout stejně jako soubor ve Finderu.

Nové okno od začátku upravuje `kind: crossword`. Tentýž druh dokumentu určuje
rozměr, role buněk, všechna místa pro vodorovná a svislá hesla i dosud
doplněný obsah. Prázdná i částečně vyplněná křížovka může sloužit jako
šablona; vyplnění proto její datový druh nemění.
Každé heslo může mít legendu uvnitř mřížky, nebo číslo a legendu pod ní;
oba způsoby lze v jedné křížovce kombinovat. Místo se vybírá kliknutím v
náhledu nebo v tabulce. Dvojklik na sloupec **Heslo** nebo **Nápověda** upraví
oba údaje přímo v příslušném řádku; Enter nebo opuštění řádku změnu
uloží, Escape ji zahodí. Vyprázdnění obou buněk nebo klávesa Delete heslo
odstraní. Dokument může zůstat prázdný, být rozpracovaný nebo hotový a v každém
z těchto stavů jej lze uložit a znovu použít jako základ další práce.

Rozměr křížovky se mění tažením kteréhokoli okraje náhledu; levý a pravý
okraj mění počet sloupců, horní a dolní počet řádků a rohy oba rozměry
současně. Nový rozměr se použije po puštění tlačítka. Změna rozměru znovu
vytvoří rozvržení; obsahuje-li dokument doplněná hesla nebo tajenku, editor si
nejprve vyžádá potvrzení. Prázdnou tiskovou křížovku lze exportovat do PDF
kdykoli, samostatné řešení až po vyplnění všech hesel.

Nabídka **Soubor** otevírá existující `kind: crossword` v dalším okně.
Na macOS používá zkratky `⌘N`, `⌘O`,
`⌘S`, `⇧⌘S` a `⌘W`; na ostatních systémech odpovídající `Ctrl+N`,
`Ctrl+O`, `Ctrl+S`, `Ctrl+Shift+S` a `Ctrl+W`. Poslední z nich zavře pouze
dané okno; pokud obsahuje neuložené změny, editor se zeptá na jejich
uložení. Po zavření posledního okna zůstane aplikace spuštěná bez
dokumentu. Každé otevřené okno je nezávislé; změna jednoho proto obsah
druhého neovlivní.

Nabídka **Okno** uvádí všechna otevřená dokumentová okna. Aktuální okno
označí a výběrem jiné položky přenese příslušný dokument dopředu. Volba
**Zdroj YAML** otevře samostatné okno s neupravitelnou YAML podobou
aktivního dokumentu. Zdroj lze posouvat a jeho text označovat a kopírovat. Při
přepnutí dokumentu nebo změně jeho obsahu se zdroj automaticky aktualizuje.

Nabídka **Nápověda** otevře [repozitář Křížovkáře na GitHubu](https://github.com/Glutexo/krizovkar)
ve výchozím webovém prohlížeči.

Podnabídka **Soubor → Otevřít poslední** uchovává mezi spuštěními až
deset naposledy otevřených nebo uložených dokumentů. Neexistující soubor
při pokusu o otevření ze seznamu odstraní; celý seznam smaže volba **Vymazat
nabídku**.

Podnabídka **Soubor → Exportovat** nabízí výstupy podle právě otevřeného
dokumentu. Formát stránky se volí přímo v dialogu vybraného exportu; poté
naváže systémový dialog pro výběr umístění PDF. Tisková podoba bez písmen je
dostupná vždy; řešení se zpřístupní po vyplnění všech hesel.

Hesla s vepsanou legendou mají místo pro nápovědu přímo v předem vytvořené
mřížce. Hesla s vnější legendou dostanou číslo a nápovědu pod mřížkou. Ruční
zadávání souřadnic ani směru proto není potřeba. Nesprávnou délku, opakované
heslo nebo rozporné písmeno aplikace odmítne konkrétní zprávou. Editor zatím
nezadává tajenky, vlastní pomůcku ani automatické vyplnění ze slovníku.

Export do PDF používá LuaLaTeX a vyžaduje stejnou instalaci TeX Live
jako příkaz `render`.

GUI vyžaduje Python 3.14.6 nebo novější sestavený s Tk 9.0 nebo novějším.
Modul `tkinter` je součástí standardní knihovny Pythonu, konkrétní verzi Tk
ale určuje použité sestavení Pythonu. Dostupnou verzi vypíše:

```shell
uv run python -c 'import tkinter as tk; print(tk.TkVersion)'
```

## Zaměření

Projekt má postupně nabídnout zejména:

- tvorbu švédských křížovek s legendami přímo v mřížce,
- tvorbu klasických a dalších typů křížovek,
- otevřený datový formát oddělený od uživatelského rozhraní,
- kontrolu mřížky, výrazů a křížení,
- export pro tisk i digitální použití.

Experimentální plnění ověřuje základní práci se slovníkem a křížením;
konkrétní rozsah první funkční verze bude popsán v roadmapě.

## Datový model

Křížovkář rozlišuje tři samostatné druhy YAML dokumentů:

- `kind: specification` je vstupní zadání se slovy, nápovědami, tajenkami a pravidly skládání,
- `kind: crossword` je prázdná, rozpracovaná nebo hotová editovatelná
  křížovka, kterou lze v libovolném stavu použít jako šablonu,
- `kind: grid` je mřížka s konkrétními rolemi buněk a volitelně již doplněnými
  písmeny a legendami, kterou lze přímo vykreslit.

```text
umístěné specification + volba rozvržení → generování šablony → crossword
rozměr + volba rozvržení → generování šablony → crossword
crossword + ruční doplňování → crossword → grid → LaTeX → PDF
crossword + slovník → fill → crossword → grid → LaTeX → PDF
```

[Nevyplněná šablona](examples/template-unfilled.yaml) i
[minimální hotová křížovka](examples/crossword-minimal.yaml) proto používají
stejný `kind: crossword`. Dokument může obsahovat libovolný počet doplněných
hesel; automatické `fill` doplní pouze zbývající místa.

Nejmenší platná cílová mřížka zatím určuje pouze rozměr:

```yaml
format: krizovkar
kind: grid
version: 1
grid:
  width: 15
  height: 10
```

Editovatelná křížovka každému heslu určuje stabilní identifikátor, začátek, směr a
délku; matice buněk rozlišuje budoucí písmena, vepsané legendy, pomůcku a
nevyplňovaná pole. Hustá nevyplněná křížovka nechá odpovědi a texty legend
neznámé, křížovka převedená ze zadání je naopak uchová jako předem doplněný
obsah míst. Ukazuje to [šablona ze zadání](examples/template-from-specification.yaml).

Šablona může navíc rezervovat jedno nebo více míst pro části tajenky.
Známá tajenka se ukládá jako seznam slov bez mezer a interpunkce, aby se
neztratila povolená místa budoucího rozdělení. `word_count` u každé části
určuje, kolik po sobě jdoucích slov se spojí do příslušného místa. Ukazuje
to [šablona s tajenkou](examples/template-secret.yaml). Pokud konkrétní znění
zatím není známé, `words` i `word_count` se vynechají a zůstanou jen
připravená místa.

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

Význam dokumentů popisuje [specifikace datového modelu](docs/datovy-model.md).
Strojová pravidla jsou oddělená v [JSON Schema zadání](src/krizovkar/schemas/specification-v1.schema.json),
[JSON Schema editovatelné křížovky](src/krizovkar/schemas/crossword-v1.schema.json) a
[JSON Schema cílové mřížky](src/krizovkar/schemas/grid-v1.schema.json).

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
`latex` a `render` nepovinná. Bez ní příkaz zapíše výsledný
YAML, textový LaTeX nebo binární PDF na standardní výstup, takže jej lze
přesměrovat nebo předat dalšímu programu:

```shell
uv run krizovkar template examples/specification-placed-words.yaml \
  --layout swedish > build/placed-template.yaml
uv run krizovkar template --width 15 --height 10 > build/template.yaml
uv run krizovkar fill build/template.yaml slovnik.json \
  > build/filled-crossword.yaml
uv run krizovkar grid build/filled-crossword.yaml > build/filled-grid.yaml
uv run krizovkar latex build/filled-grid.yaml > build/filled-grid.tex
uv run krizovkar render build/filled-grid.yaml > build/filled-grid.pdf
```

Stavová hláška jde v tomto režimu na standardní chybový výstup a výsledná data neznečistí. Při zadaném `--output` se dál zapisuje atomicky do souboru, existující soubor se bez `--force` nepřepíše a stavová hláška se vypíše na standardní výstup.

Místo vstupního souboru přijímají příkazy `template`, `grid`, `fill`,
`validate`, `latex` a `render` také `-`, které znamená standardní
vstup. U `template` jde o vstupní zadání. U příkazu `fill` lze tímto
způsobem načíst křížovku nebo slovník, ale ne oba vstupy současně.
Výstupy lze díky tomu spojovat přímo rourou. Křížovka použitá jako šablona
se může převést na LaTeX bez mezikroku:

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

## Vygenerování šablony

Umístěné zadání převede na šablonu volitelný poziční argument:

```shell
uv run krizovkar template examples/specification-placed-words.yaml \
  --layout swedish \
  --output build/template-from-specification.yaml
```

Převod zachová rozměr, odpovědi, legendy, tajenky, jejich zadání i pomůcku.
Každé umístěné běžné nebo tajenkové slovo se stane doplněným slotem.
`--layout swedish` rezervuje volnou buňku bezprostředně vlevo od vodorovného
hesla nebo nad svislým heslem. Pokud tam není místo nebo by legenda překryla
písmeno, převod skončí s konkrétní chybou. `--layout numbered` samostatné
legendové buňky nepotřebuje a texty připraví jako vnější číslované legendy.

Rozměr i tajenky už v tomto režimu určuje zadání. Volby `--width`,
`--height`, `--seed` a volby tajenky proto nelze se vstupním souborem
kombinovat.

Bez vstupního zadání vygeneruje stejný příkaz hustou nevyplněnou šablonu
bez slovníku a bez znalosti budoucích odpovědí. Výchozí rozvržení je švédské:

```shell
uv run krizovkar template \
  --width 15 \
  --height 10 \
  --output build/template.yaml
```

Číslované (čárkované) rozvržení zvolí `--layout numbered`:

```shell
uv run krizovkar template \
  --layout numbered \
  --width 15 \
  --height 10 \
  --output build/numbered-template.yaml
```

Stejné rozvržení a rozměry vytvoří stejnou šablonu. Švédský
generátor rozdělí plochu na písmenné obdélníky, legendové buňky a jejich
nevyplňované průsečíky. Číslovaná varianta ponechá všechny buňky písmenné,
obě osy rozdělí silnými předěly a budoucí legendy umístí vně mřížky.
Obě rozvržení používají délky hesel 3 až 8 a každému vodorovnému i
svislému heslu přidělí vlastní místo. Příkaz existující soubor nepřepíše
bez volby `--force`.

Tajenku lze při generování šablony zadat čtyřmi způsoby:

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

Platnou křížovku lze v kterémkoli stavu bez slovníku převést na cílovou mřížku:

```shell
uv run krizovkar grid build/template.yaml \
  --output build/unfilled-grid.yaml
```

Převod zachová nevyplňovaná, legendová a pomocná pole, čísla a silné
předěly číslovaného rozvržení, zvýraznění tajenek, jejich zobáčky a zadání.
U husté nevyplněné šablony zůstanou písmena a texty legend prázdné.
Šablona vytvořená ze zadání naopak přenese pevné odpovědi, legendy a
slova pomůcky. Bez mezikroku ji lze vysázet příkazem
`krizovkar latex build/template.yaml` nebo z ní rovnou sestavit PDF příkazem
`krizovkar render build/template.yaml`.

Prázdná místa šablony lze později vyplnit ze slovníku:

```shell
uv run krizovkar fill build/template.yaml slovnik.json \
  --seed 10 \
  --output build/filled-crossword.yaml
```

Plnění funguje pro prázdné, ručně vytvořené, částečně vyplněné i hotové křížovky.
Doplněná hesla zachová; pro každé zbývající místo vybere heslo odpovídající délky,
zachová shodná písmena na kříženích a stejnou odpověď nepoužije dvakrát.
Odpověď a legendu uloží přímo do původního slotu. Vstupem i výsledkem je
tentýž druh editovatelného dokumentu `kind: crossword`. Ten lze dál upravovat,
znovu použít jako základ nebo převést na cílovou mřížku:

```shell
uv run krizovkar grid build/filled-crossword.yaml \
  --output build/filled-grid.yaml
```

Při převodu dostane slot s vepsanou legendovou buňkou švédskou legendu;
slot bez ní dostane číslo a vnější legendu. Stejná křížovka, slovník a
seed vytvoří stejnou vyplněnou křížovku.

Známou tajenku uloženou v křížovce `fill` doplní automaticky a její
místa nevyhledává ve slovníku. Rezervuje-li dokument jen prázdná tajenková
místa, předá se konkrétní text pomocí `--secret` nebo opakovaného
`--secret-part`. Stejné volby lze použít i bez předchozí rezervace; plnění
pak vhodná místa tajenky samo vybere. Jednotlivé části při plnění dostanou
legendy `1. část tajenky`, `2. část tajenky` a tak dále; následný převod
jejich pole ve výsledné mřížce zvýrazní.

## Slovník

Příkaz `fill` přijímá slovník jako JSON objekt. Klíčem je heslo
složené z podporovaných velkých písmen včetně diakritiky a hodnotou neprázdný
seznam možných legend v preferovaném pořadí:

```json
{
  "OCHOČENÁ": ["Zkrocená"],
  "ŘEKA": ["Vodní tok"]
}
```

Nejprve se vygeneruje nevyplněná šablona, potom se naplní slovníkem a
nakonec se převede nebo rovnou vykreslí:

```shell
uv run krizovkar template --width 15 --height 10 \
  --output build/template.yaml
uv run krizovkar fill build/template.yaml slovnik.json \
  --seed 10 --output build/filled-crossword.yaml
uv run krizovkar render build/filled-crossword.yaml \
  --output build/filled-crossword.pdf
```

Rozvržení `numbered` se volí u prvního příkazu `template`; konkrétní
nebo rezervovaná tajenka se zadá při vygenerování šablony nebo při jejím
pozdějším plnění. Stejná šablona, slovník a seed vytvoří stejný vyplněný
dokument.

Pokud švédská maska obsahuje více písmenných obdélníků oddělených legendovými osami, jejich hesla se navzájem nekříží. Kvalitativní validace proto upozorní, že výsledná slova tvoří oddělené ostrovy; číslovaná varianta má naproti tomu souvislou písmennou plochu.

Ve švédské variantě legendy pokrývají horní a levou stranu každého písmenného bloku. Na horním okraji chybí legenda jen ve sloupci s dalšími vnitřními legendami a na levém okraji jen v řádku s dalšími vnitřními legendami. Každá vepsaná legenda má jediný text a právě jeden možný směr navazujícího hesla, takže nepotřebuje šipku. První experimentální verze zatím nevytváří pomůcku a nehodnotí jazykovou kvalitu hesel. Zdrojový slovník není součástí projektu; uživatel musí mít právo jeho obsah použít.

## Validace

Datový formát a pravidla dobré křížovky jsou dvě oddělené vrstvy. Příkaz `validate` nejprve ověří, zda lze YAML bezpečně načíst jako cílovou mřížku, a potom posoudí společná pravidla jejího rozložení:

```shell
uv run krizovkar validate build/filled-grid.yaml
```

Chyba znamená neplatný nebo vnitřně rozporný datový model a příkaz skončí návratovým kódem `2`. Varování znamená platnou mřížku, kterou lze dál zpracovat a vykreslit, ale porušuje některé pravidlo kvality; návratový kód zůstává `0`.

Validátor nepřiřazuje celé mřížce jeden druh. U každého začátku hesla samostatně přijme bezprostředně předcházející legendovou buňku nebo číslo; silný předěl přitom zakládá nové heslo. Proto kontroluje vepsané legendy i ve mřížce, která zároveň obsahuje `number`, `bars` nebo vnější `clues`. Dále varuje zejména před směrovými šipkami vepsaných legend, nesouladem počtu jejich textů a navazujících směrů a oddělenými písmennými ostrovy. Zobáčky tajenky tato varování nevyvolávají.

## Vytvoření LaTeXu a PDF

Projekt vyžaduje Python 3.14.6 nebo novější; soubor `.python-version`
pro vývoj připíná verzi 3.14.6. Pythonové závislosti lze nainstalovat pomocí
[uv](https://docs.astral.sh/uv/):

```shell
uv sync
```

Příkaz `latex` převede ukázkový YAML na samostatný textový LaTeXový dokument:

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

Stejné dva kroky provede najednou příkaz `render`. LaTeXový zdroj vytvoří
v dočasném adresáři a PDF sestaví výhradně jeho překladem pomocí příkazu
`lualatex`:

```shell
uv run krizovkar render examples/grid-random-letters.yaml \
  --page-format A4 \
  --output build/random-letters.pdf
```

Vstupem `latex` i `render` může být cílová mřížka `kind: grid` nebo
editovatelná křížovka `kind: crossword`; křížovka se automaticky převede na
mřížku bez slovníku bez ohledu na míru vyplnění.
Volba `--page-format` přijímá `A0` až `A6`, `Letter` a `Legal`,
nerozlišuje velikost písmen a její výchozí hodnota je `A4`. Obsah se podle
potřeby zmenší tak, aby zůstal na jedné stránce zvoleného formátu.

U vyplněné cílové mřížky LaTeX i PDF standardně zobrazí písmena. Pro jejich
skrytí přidej k příkazu `latex` nebo `render` volbu `--blank`; nevyplněná
křížovka a mřížka zůstanou prázdné i bez této volby:

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

Před odevzdáním změny se spouští kontrola Ruffem, testy Pytestem a
kompilace všech Pythoních modulů:

```shell
uv run ruff check .
uv run pytest
uv run python -m compileall -q src tests
```

## Vývoj

Pravidla spolupráce jsou v [CONTRIBUTING.md](CONTRIBUTING.md). Každá dokončená logická změna se po kontrole samostatně commitne a ihned odešle na GitHub.

## Licence

Obsah repozitáře je uvolněn pod [CC0 1.0 Universal](LICENSE). Autoři se v maximálním rozsahu dovoleném právem vzdávají autorských a souvisejících práv.
