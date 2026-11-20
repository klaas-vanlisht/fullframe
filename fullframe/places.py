"""Which countries is a story about? Matches country names, demonyms, capitals and big cities in
headlines (case-sensitive, so "chile" peppers or "brussels sprouts" stay out). Used for the
Local and International views. Ambiguous words (Turkey, Georgia, Jordan, Chad, ...) are left out
on purpose; the AI's country tags fill those gaps for the biggest stories.
"""
import re

GAZETTEER = {
    "US": ("United States", [r"U\.S\.(?!\w)", r"US", r"United States", r"USA", r"(?<!Latin )(?<!South )(?<!Central )(?<!North )Americans?"]),
    "UK": ("United Kingdom", [r"United Kingdom", r"U\.K\.(?!\w)", r"UK", r"Britain", r"British", r"England", r"Scotland", r"Scottish",
                              r"Wales", r"Welsh", r"London", r"Downing Street", r"Northern Ireland", r"Manchester", r"Birmingham"]),
    "IE": ("Ireland", [r"(?<!Northern )Ireland", r"Irish", r"Dublin", r"Cork"]),
    "CA": ("Canada", [r"Canada", r"Canadians?", r"Ottawa", r"Toronto", r"Montreal", r"Vancouver", r"Quebec", r"Alberta", r"Ontario"]),
    "AU": ("Australia", [r"Australia", r"Australians?", r"Sydney", r"Melbourne", r"Canberra", r"Brisbane", r"Queensland"]),
    "NZ": ("New Zealand", [r"New Zealand", r"Auckland", r"Christchurch"]),
    "IN": ("India", [r"India", r"Indians?(?! (?:tribes?|reservations?|Ocean))", r"New Delhi", r"Delhi", r"Mumbai", r"Bengaluru",
                     r"Bangalore", r"Kolkata", r"Chennai", r"Hyderabad", r"Modi"]),
    "BE": ("Belgium", [r"Belgium", r"Belgians?", r"Brussels(?! sprouts)", r"Antwerp", r"Ghent", r"Flanders", r"Flemish", r"Wallonia",
                       r"Walloon", r"Li[eè]ge", r"Bruges", r"Charleroi", r"Leuven", r"Mechelen"]),
    "NL": ("Netherlands", [r"Netherlands", r"Dutch", r"Amsterdam", r"Rotterdam", r"The Hague", r"Utrecht"]),
    "LU": ("Luxembourg", [r"Luxembourg"]),
    "FR": ("France", [r"France", r"French", r"Paris(?! Hilton)", r"Macron", r"Marseille", r"Lyon", r"Toulouse"]),
    "DE": ("Germany", [r"Germany", r"Germans?", r"Berlin", r"Munich", r"Hamburg", r"Frankfurt", r"Cologne", r"Bundestag"]),
    "CH": ("Switzerland", [r"Switzerland", r"Swiss", r"Geneva", r"Zurich", r"Z[uü]rich", r"Bern"]),
    "AT": ("Austria", [r"Austria", r"Austrians?", r"Vienna"]),
    "IT": ("Italy", [r"Italy", r"Italians?", r"Rome", r"Milan", r"Naples", r"Venice", r"Sicily", r"Florence", r"Vatican"]),
    "ES": ("Spain", [r"Spain", r"Spanish", r"Madrid", r"Barcelona", r"Catalonia", r"Catalan", r"Valencia", r"Seville"]),
    "PT": ("Portugal", [r"Portugal", r"Portuguese", r"Lisbon", r"Porto"]),
    "GR": ("Greece", [r"Greece", r"Greek", r"Athens"]),
    "PL": ("Poland", [r"Poland", r"Poles", r"Polish", r"Warsaw", r"Krak[oó]w"]),
    "CZ": ("Czechia", [r"Czechia", r"Czech", r"Prague"]),
    "SK": ("Slovakia", [r"Slovakia", r"Slovak", r"Bratislava"]),
    "HU": ("Hungary", [r"Hungary", r"Hungarians?", r"Budapest", r"Orb[aá]n"]),
    "RO": ("Romania", [r"Romania", r"Romanians?", r"Bucharest"]),
    "BG": ("Bulgaria", [r"Bulgaria", r"Bulgarians?", r"Sofia"]),
    "HR": ("Croatia", [r"Croatia", r"Croatians?", r"Zagreb"]),
    "RS": ("Serbia", [r"Serbia", r"Serbians?", r"Belgrade"]),
    "UA": ("Ukraine", [r"Ukraine", r"Ukrainians?", r"Kyiv", r"Kiev", r"Kharkiv", r"Odesa", r"Odessa", r"Zelensky[iy]?", r"Donbas", r"Crimea"]),
    "RU": ("Russia", [r"Russia", r"Russians?", r"Moscow", r"Kremlin", r"Putin", r"St\.? Petersburg"]),
    "BY": ("Belarus", [r"Belarus", r"Belarusian", r"Minsk", r"Lukashenko"]),
    "SE": ("Sweden", [r"Sweden", r"Swedish", r"Swedes", r"Stockholm"]),
    "NO": ("Norway", [r"Norway", r"Norwegian", r"Oslo"]),
    "DK": ("Denmark", [r"Denmark", r"Danish", r"Danes", r"Copenhagen"]),
    "GL": ("Greenland", [r"Greenland"]),
    "FI": ("Finland", [r"Finland", r"Finnish", r"Finns", r"Helsinki"]),
    "IS": ("Iceland", [r"Iceland", r"Icelandic", r"Reykjavik"]),
    "EE": ("Estonia", [r"Estonia", r"Estonian", r"Tallinn"]),
    "LV": ("Latvia", [r"Latvia", r"Latvian", r"Riga"]),
    "LT": ("Lithuania", [r"Lithuania", r"Lithuanian", r"Vilnius"]),
    "TR": ("Türkiye", [r"T[uü]rkiye", r"Turkish", r"Turks", r"Ankara", r"Istanbul", r"Erdo[gğ]an"]),
    "IL": ("Israel", [r"Israel", r"Israelis?", r"Jerusalem", r"Tel Aviv", r"Netanyahu", r"IDF"]),
    "PS": ("Palestine", [r"Gaza", r"Gazans?", r"Palestin\w*", r"West Bank", r"Hamas", r"Ramallah"]),
    "LB": ("Lebanon", [r"Lebanon", r"Lebanese", r"Beirut", r"Hezbollah"]),
    "SY": ("Syria", [r"Syria", r"Syrians?", r"Damascus", r"Aleppo"]),
    "IQ": ("Iraq", [r"Iraq", r"Iraqis?", r"Baghdad"]),
    "IR": ("Iran", [r"Iran", r"Iranians?", r"Tehran", r"Khamenei"]),
    "SA": ("Saudi Arabia", [r"Saudi", r"Saudis", r"Riyadh"]),
    "AE": ("United Arab Emirates", [r"UAE", r"United Arab Emirates", r"Dubai", r"Abu Dhabi", r"Emirati"]),
    "QA": ("Qatar", [r"Qatar", r"Qatari", r"Doha"]),
    "YE": ("Yemen", [r"Yemen", r"Yemeni", r"Houthis?", r"Sanaa"]),
    "EG": ("Egypt", [r"Egypt", r"Egyptians?", r"Cairo"]),
    "AF": ("Afghanistan", [r"Afghanistan", r"Afghans?", r"Kabul", r"Taliban"]),
    "PK": ("Pakistan", [r"Pakistan", r"Pakistanis?", r"Islamabad", r"Karachi", r"Lahore"]),
    "BD": ("Bangladesh", [r"Bangladesh", r"Bangladeshi", r"Dhaka"]),
    "LK": ("Sri Lanka", [r"Sri Lanka", r"Sri Lankan", r"Colombo"]),
    "CN": ("China", [r"China", r"Chinese", r"Beijing", r"Shanghai", r"Shenzhen", r"Xi Jinping", r"Xi(?= (?:says|said|and|to|meets|warns|calls))"]),
    "HK": ("Hong Kong", [r"Hong Kong"]),
    "TW": ("Taiwan", [r"Taiwan", r"Taiwanese", r"Taipei"]),
    "JP": ("Japan", [r"Japan", r"Japanese", r"Tokyo", r"Osaka", r"Kyoto"]),
    "KR": ("South Korea", [r"South Korea", r"South Koreans?", r"Seoul"]),
    "KP": ("North Korea", [r"North Korea", r"North Koreans?", r"Pyongyang", r"Kim Jong[- ]?un"]),
    "VN": ("Vietnam", [r"Vietnam", r"Vietnamese", r"Hanoi"]),
    "TH": ("Thailand", [r"Thailand", r"Thai", r"Bangkok"]),
    "PH": ("Philippines", [r"Philippines", r"Philippine", r"Filipinos?", r"Manila"]),
    "ID": ("Indonesia", [r"Indonesia", r"Indonesians?", r"Jakarta", r"Bali"]),
    "MY": ("Malaysia", [r"Malaysia", r"Malaysians?", r"Kuala Lumpur"]),
    "SG": ("Singapore", [r"Singapore", r"Singaporeans?"]),
    "MX": ("Mexico", [r"Mexico", r"Mexicans?", r"Sheinbaum", r"Tijuana", r"Guadalajara", r"Monterrey"]),
    "BR": ("Brazil", [r"Brazil", r"Brazilians?", r"S[aã]o Paulo", r"Rio de Janeiro", r"Bras[ií]lia", r"Lula"]),
    "AR": ("Argentina", [r"Argentina", r"Argentines?", r"Argentinians?", r"Buenos Aires", r"Milei"]),
    "VE": ("Venezuela", [r"Venezuela", r"Venezuelans?", r"Caracas", r"Maduro"]),
    "CO": ("Colombia", [r"Colombia", r"Colombians?", r"Bogot[aá]"]),
    "CL": ("Chile", [r"Chile", r"Chileans?", r"Santiago"]),
    "PE": ("Peru", [r"Peru", r"Peruvians?", r"Lima"]),
    "CU": ("Cuba", [r"Cuba", r"Cubans?", r"Havana"]),
    "HT": ("Haiti", [r"Haiti", r"Haitians?", r"Port-au-Prince"]),
    "ZA": ("South Africa", [r"South Africa", r"South Africans?", r"Johannesburg", r"Cape Town", r"Pretoria"]),
    "NG": ("Nigeria", [r"Nigeria", r"Nigerians?", r"Lagos", r"Abuja"]),
    "KE": ("Kenya", [r"Kenya", r"Kenyans?", r"Nairobi"]),
    "ET": ("Ethiopia", [r"Ethiopia", r"Ethiopians?", r"Addis Ababa"]),
    "SD": ("Sudan", [r"(?<!South )Sudan", r"(?<!South )Sudanese", r"Khartoum", r"Darfur"]),
    "SS": ("South Sudan", [r"South Sudan"]),
    "CD": ("DR Congo", [r"Congo", r"Congolese", r"Kinshasa", r"Goma"]),
    "SO": ("Somalia", [r"Somalia", r"Somalis?", r"Mogadishu"]),
    "LY": ("Libya", [r"Libya", r"Libyans?", r"Tripoli"]),
    "MA": ("Morocco", [r"Morocco", r"Moroccans?", r"Rabat", r"Casablanca"]),
    "DZ": ("Algeria", [r"Algeria", r"Algerians?", r"Algiers"]),
    "TN": ("Tunisia", [r"Tunisia", r"Tunisians?", r"Tunis"]),
}

COUNTRY_NAMES = {code: name for code, (name, _) in GAZETTEER.items()}
_RES = {code: re.compile(r"(?<![\w.])(?:%s)(?![\w])" % "|".join(pats)) for code, (_, pats) in GAZETTEER.items()}


def detect(text):
    """Country codes mentioned in a piece of text (headline, summary)."""
    if not text:
        return set()
    found = {code for code, rx in _RES.items() if rx.search(text)}
    # "Brussels" is often shorthand for the EU institutions: only count Belgium if the text
    # names something Belgian besides "Brussels", or isn't about EU politics
    if "BE" in found and not _BE_STRONG.search(text) and _EU_CONTEXT.search(text):
        found.discard("BE")
    return found


_BE_STRONG = re.compile(r"Belgi|Antwerp|Ghent|Flanders|Flemish|Wallon|Li[eè]ge|Bruges|Charleroi|Leuven|Mechelen")
_EU_CONTEXT = re.compile(r"\b(?:EU|E\.U\.|European|Europe|Brexit|Commission|Council|Parliament|NATO|summit|von der Leyen|"
                         r"Burnham|Starmer|trade|tariffs?|bloc|Kallas|Costa|member states?)\b")
