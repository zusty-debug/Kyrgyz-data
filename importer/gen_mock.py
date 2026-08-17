"""
Mock-data generator. Produces a large TXT file in the *real* format we
discovered: TAB-separated fields, optional DOB or NULL, optional 2nd-line.
"""
import os, random
random.seed(42)

FIRST_M = ["Александр", "Сергей", "Иван", "Дмитрий", "Алексей", "Руслан",
           "Нурлан", "Бакыт", "Эрлан", "Азамат", "Таалай", "Тимур",
           "Владимир", "Андрей", "Михаил", "Жаныбек", "Кайрат", "Шайбек",
           "Айбек", "Улан"]
FIRST_F = ["Галина", "Мария", "Татьяна", "Елена", "Наталья", "Ольга",
           "Айгерим", "Айсулуу", "Диларам", "Элизат", "Нургуль",
           "Айнура", "Мадина", "Жамиля", "Светлана", "Виктория",
           "Салтанат", "Канышай", "Гульзат", "Умугульсултан"]
LAST_M = ["Капинос", "Найхович", "Карабалаев", "Кельгенбаев", "Токтоналиев",
          "Козлов", "Деркенбаев", "Гашизов", "Суйруев", "Токторбаев",
          "Ельве", "Усубакунов", "Атаходжаев", "Азанкулов", "Бурканов",
          "Соломыкин", "Алиев", "Бексултанов", "Жунусов", "Иванов",
          "Петров", "Сидоров", "Морозов", "Орлов", "Громов"]
LAST_F = ["Карабалаева", "Соломыкина", "Онофрейчук", "Атаходжаева",
          "Бурканова", "Алимжанова", "Лапшакова", "Элебаева",
          "Калдыбаева", "Мамбетова", "Касымова", "Ибрагимова",
          "Юдахина", "Шамсинская", "Московская", "Литовская"]
PATR_M = ["ович", "евич"]
PATR_F = ["овна", "евна"]

REGIONS = [
    ("Ыссык Кульская обл.", ["Каракол", "Балыкчы", "Чолпон-Ата"]),
    ("Чуйская обл.", ["Бишкек", "Токмок", "Кара Балта", "Кант"]),
    ("Ошская обл.", ["Ош", "Кара-Суу", "Узген"]),
    ("Баткенская область", ["Исфана", "Баткен", "Кызыл-Кия"]),
    ("Нарынская обл.", ["Нарын", "Ат-Башы", "Кочкорка"]),
    ("Джалал-Абадская обл.", ["Джалал-Абад", "Таш-Кумыр", "Кара-Куль"]),
    ("Таласская обл.", ["Талас", "Кара-Буура"]),
]

STREETS = ["Московская", "Киевская", "Ленина", "Советская", "Ахунбаева",
           "К.Акиева", "Манаса", "Эркиндик", "Чуй", "Юдахина", "Литовская",
           "Токтогула", "Шамсинская", "Гебзе", "Додосьян", "Жакшыбай",
           "Фуркат", "Ашырбек Ажы", "Ташкентская", "Свердловский р н",
           "Тонский р н", "Иссыккульский р н", "Тюпский р н",
           "ЖАйылский р н", "Кеминский р н", "Лейлекский район",
           "Карасуйский р н", "Сокулукский р н"]

ORGS = [
    "Общество с ограниченной ответственностью",
    "ОсОО",
    "ЗАО",
    "ОАО",
]

def gen_org_name(rng):
    base = rng.choice(ORGS)
    suffix = rng.choice(["MURAT MEDIA", "BUILD TRADING", "AGRO FARM",
                           "TRANS LOGISTIC", "FOOD PLUS", "TECH SOLUTIONS",
                           "SOFT LAB", "AUTO CENTER", "SERVICE GROUP"])
    return f"{base}\t {suffix}"

def gen_name(rng, gender):
    if gender == "M":
        first = rng.choice(FIRST_M)
        last = rng.choice(LAST_M)
        patr = rng.choice(PATR_M)
    else:
        first = rng.choice(FIRST_F)
        last = rng.choice(LAST_F)
        patr = rng.choice(PATR_F)
    # 70% of the time put patronymic in its own tab-field
    if rng.random() < 0.7:
        return last + " " + first, patr
    return f"{last} {first} {patr}", ""

def gen_record(rng, idx):
    is_org = rng.random() < 0.04  # 4% organizations
    if is_org:
        name_a = gen_org_name(rng)
    else:
        gender = rng.choice(["M", "F"])
        a, b = gen_name(rng, gender)
        name_a = a
        name_b = b

    region, cities = rng.choice(REGIONS)
    city = rng.choice(cities)
    street = rng.choice(STREETS)
    house_no = rng.randint(1, 200)

    # Build person_id (DDMMYYYY + 6 digits)
    year = rng.randint(1940, 2007)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    pid = f"{day:02d}{month:02d}{year:04d}{rng.randint(0, 999999):06d}"
    if len(pid) != 14:
        pid = (pid + "000000")[:14]

    has_dob = rng.random() < 0.6
    fields = []
    if is_org:
        fields.append(name_a)
    else:
        fields.append(name_a)
        if name_b:
            fields.append(name_b)
    fields.append(region)
    fields.append(f"г. {city}")
    if not street.startswith(("р н", "р-н")):
        fields.append(f"ул. {street}")
    else:
        fields.append(street)
    fields.append(f"д. {house_no}")
    if rng.random() < 0.5:
        fields.append(f"кв. {rng.randint(1, 80)}")
    fields.append(pid)
    if has_dob:
        fields.extend([str(year), f"{month:02d}", f"{day:02d}"])
    else:
        fields.append("NULL")

    line = "\t".join(fields)
    return line

def main():
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "data.txt")
    n = 5000
    with open(out, "w", encoding="utf-8") as fh:
        for i in range(n):
            line = gen_record(random, i)
            if random.random() < 0.1:
                # 10% chance: split into 2 physical lines mid-location
                # Insert a newline just before the street token (find 3rd "\t")
                tabs = line.split('\t')
                if len(tabs) > 3:
                    pivot = len(tabs) // 2
                    line = '\t'.join(tabs[:pivot]) + '\n' + '\t'.join(tabs[pivot:])
            fh.write(line + '\n')
    print(f"Wrote {n} synthetic records to {out}")

if __name__ == "__main__":
    main()
