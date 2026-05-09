#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VML 1.0 Validator

Usage:
    python vml_validator.py <file.vml>

Ниже представлен валидатор VML 1.0 на Python. Он проверяет:

- наличие обязательных тегов `<a>` и `<&>`;
- корректность синтаксиса тегов (угловые скобки, допустимые имена);
- экранирование служебных последовательностей;
- корректную вложенность парных тегов (`<nn>`, `<l-...>`);
- базовую иерархию (автор → цикл → стихотворение → строки);
- отсутствие запрещённых вложений (дата/место внутри строки);
- правильное завершение тегов и конец файла.

Валидатор не проверяет семантику метрических тегов (`<m-...>`) и не анализирует числовые значения (например, корректность `NUM` в `<l-NUM>`), поскольку это выходит за рамки синтаксического контроля.
"""

import sys
import re

# ------------------------------------------------------------
# Допустимые теги и их типы
# ------------------------------------------------------------
SINGLE_TAGS = {'a', '&', 'n', '#', '%', '*', 'rm'}          # одиночные (не требуют закрытия)
PAIR_TAGS_OPEN = {'nn', 'l-'}                               # открывающие парные теги (l- — префикс)
PAIR_TAGS_CLOSE = {'/nn', '/l-'}                            # закрывающие
# Полные имена парных тегов: 'nn' и 'l-xxx' (динамически)

# Регулярное выражение для распознавания тегов (неэкранированных)
TAG_PATTERN = re.compile(r'(?<!\\)<([^>\s]+)>')

# Список всех валидных имён тегов (без учёта динамических l-*)
VALID_TAG_NAMES = {
    'a', 'n', '&', '#', '%', '*', 'rm',     # одиночные
    'nn', '/nn',                            # парный цикл
    # l-* и /l-* будут проверяться динамически
}


# ------------------------------------------------------------
# Класс ошибки
# ------------------------------------------------------------
class VMLError:
    def __init__(self, line_num, message):
        self.line_num = line_num
        self.message = message

    def __str__(self):
        return f"Ошибка в строке {self.line_num}: {self.message}"


# ------------------------------------------------------------
# Валидатор
# ------------------------------------------------------------
class VMLValidator:
    def __init__(self):
        self.errors = []
        self.lines = []           # список строк (без \n)
        self.context = {          # текущее состояние
            'author_found': False,
            'in_poem': False,           # после <&> и до конца стихотворения
            'in_cycle': False,
            'cycle_tag_line': None,
            'pair_stack': [],           # стек для парных тегов: (имя_тега, строка_открытия)
            'title_mode': False,        # режим сбора многострочного заголовка
            'poem_has_lines': False,    # после <&> были строки (хотя бы одна)
            'current_author_name': None,
        }
        # Для отслеживания строк стихотворения
        self.inside_stanza = False

    def _close_current_poem(self, line_num, reason="конец файла"):
        """Закрывает текущее стихотворение, если оно открыто."""
        if self.context['in_poem']:
            if not self.context['poem_has_lines']:
                self.errors.append(VMLError(line_num, f"Стихотворение не содержит ни одной стихотворной строки (закрыто по причине: {reason})"))
            self.context['in_poem'] = False
            self.context['poem_has_lines'] = False
            self.inside_stanza = False

    def _close_current_cycle(self, line_num, reason="закрытие цикла"):
        """Закрывает текущий цикл, если он открыт."""
        if self.context['in_cycle']:
            # Проверяем, что цикл явно закрыт (в стеке есть nn)
            if self.context['pair_stack'] and self.context['pair_stack'][-1][0] == 'nn':
                self.context['pair_stack'].pop()
            self.context['in_cycle'] = False

    def validate(self, filepath):
        """Главная точка входа: прочитать файл и запустить проверку."""
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                content = f.read()
        except FileNotFoundError:
            self.errors.append(VMLError(0, f"Файл не найден: {filepath}"))
            return False
        except UnicodeDecodeError:
            self.errors.append(VMLError(0, "Файл не в кодировке UTF-8 (BOM не допускается, но файл с BOM будет прочитан, проверьте)"))
            return False

        # Разбивка на строки с номерами (1-based)
        lines = content.splitlines()
        # Проверка на недопустимые символы \r: если строки содержат \r, splitlines() их удалит, но проверим случай CRLF
        for i, line in enumerate(lines, 1):
            if '\r' in line:
                self.errors.append(VMLError(i, "Обнаружен символ CR (\\r) – используйте только LF"))
        # Обработка пустого файла
        if not lines:
            self.errors.append(VMLError(0, "Файл пуст"))
            return False

        self.lines = lines
        for idx, line in enumerate(lines, start=1):
            self._process_line(line, idx)

        # Закрываем последнее стихотворение (если оно осталось открытым)
        if self.context['in_poem']:
            self._close_current_poem(len(self.lines), "конец файла")

        # Проверки после обработки всех строк
        if not self.context['author_found']:
            self.errors.append(VMLError(0, "Документ не содержит тега автора <a>"))
        # Проверка стека парных тегов
        if self.context['pair_stack']:
            for tag, line_num in self.context['pair_stack']:
                self.errors.append(VMLError(line_num, f"Незакрытый тег <{tag}>"))

        return len(self.errors) == 0

    def _process_line(self, line, line_num):
        # Удаляем конечные пробелы для анализа, но помним оригинал
        orig = line
        line = line.rstrip('\n')

        # Режим многострочного заголовка: продолжается до строки, содержащей <&>
        if self.context.get('title_mode', False):
            if '<&>' in line:
                self.context['title_mode'] = False
                # Обрабатываем эту строку как обычную (содержит <&>)
                self._process_line_content(line, line_num)
            # Иначе игнорируем содержимое заголовка (внутри может быть что угодно)
            return

        # Обработка содержимого строки (теги, экранирование)
        self._process_line_content(line, line_num)

    def _process_line_content(self, line, line_num):
        # Реализуем ручной поиск тегов
        i = 0
        n = len(line)
        tags = []
        while i < n:
            if line[i] == '\\' and i+1 < n and line[i+1] == '<':
                # экранированная открывающая скобка – пропускаем два символа
                i += 2
                continue
            if line[i] == '<':
                # ищем закрывающую '>'
                j = i+1
                while j < n and line[j] != '>':
                    j += 1
                if j < n:
                    # нашли тег
                    tag_content = line[i+1:j]
                    tags.append((i, tag_content))
                    i = j+1
                else:
                    # Незакрытая угловая скобка – ошибка
                    self.errors.append(VMLError(line_num, f"Незакрытая угловая скобка в строке: {line}"))
                    i += 1
            else:
                i += 1

        # Если тегов нет и строка пустая – игнорируем
        if not tags and line.strip() == '':
            return
        if not tags:
            # строка без тегов
            if not self.context.get('in_poem', False):
                self.errors.append(VMLError(line_num, f"Строка вне стихотворения: {line[:50]}..."))
            else:
                # это стихотворная строка
                self.context['poem_has_lines'] = True
            return

        # Определяем основной тег (первый из списка основных)
        main_tag = None
        for pos, tagname in tags:
            if tagname in SINGLE_TAGS or tagname in PAIR_TAGS_OPEN or tagname in PAIR_TAGS_CLOSE:
                main_tag = tagname
                break
            if tagname.startswith('l-') or tagname.startswith('m-'):
                # вспомогательные теги внутри строки – пропускаем
                continue

        # Если основного тега нет, но это внутри стихотворения – считаем строкой стиха
        if main_tag is None:
            if self.context.get('in_poem', False):
                self.context['poem_has_lines'] = True
            else:
                if tags:
                    self.errors.append(VMLError(line_num, f"Строка вне стихотворения с тегом: {tags[0][1]}"))
            return

        # Отделяем текст после тегов (для тегов, которые могут иметь значение)
        last_tag_end = tags[-1][0] + len(tags[-1][1]) + 2
        text_after_tags = line[last_tag_end:].lstrip()

        # Проверка валидности имени тега
        tag_name = main_tag
        if tag_name.startswith('l-'):
            if not re.match(r'l-[1-9][0-9]*$', tag_name):
                self.errors.append(VMLError(line_num, f"Неверный формат тега лесенки: <{tag_name}> (ожидается l-ЧИСЛО)"))
        elif tag_name.startswith('/l-'):
            if not re.match(r'/l-[1-9][0-9]*$', tag_name):
                self.errors.append(VMLError(line_num, f"Неверный закрывающий тег: <{tag_name}>"))
        elif tag_name.startswith('m-'):
            if not re.match(r'm-[SRA][A-Za-zА-Яа-я0-9*]*', tag_name):
                self.errors.append(VMLError(line_num, f"Неверный формат метрического тега: <{tag_name}>"))
        elif tag_name not in VALID_TAG_NAMES and not (tag_name.startswith('l-') or tag_name.startswith('/l-')):
            self.errors.append(VMLError(line_num, f"Неизвестный тег: <{tag_name}>"))

        # Семантическая обработка основного тега
        # --------------------------------------------------------
        if main_tag == 'a':
            # Тег автора – закрываем текущее стихотворение и цикл (если есть)
            if self.context['in_poem']:
                self._close_current_poem(line_num, "встречен тег <a>")
            if self.context['in_cycle']:
                self._close_current_cycle(line_num, "встречен тег <a>")
            self.context['author_found'] = True
            self.context['in_poem'] = False
            self.context['in_cycle'] = False
            self.context['poem_has_lines'] = False
            self.context['current_author_name'] = text_after_tags.strip()
            if not text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <a> без имени автора"))
            if self.context['pair_stack']:
                # если остались другие парные теги (l-...), это ошибка
                for tag, ln in self.context['pair_stack']:
                    self.errors.append(VMLError(ln, f"Незакрытый тег <{tag}> перед новым автором"))
                self.context['pair_stack'].clear()

        elif main_tag == 'nn':
            # Начало нового цикла – закрываем текущее стихотворение и текущий цикл (если есть)
            if self.context['in_poem']:
                self._close_current_poem(line_num, "встречен <nn> (начало нового цикла)")
            # Вложенные циклы запрещены: если уже внутри цикла, закрываем его и выдаём предупреждение? 
            # По спецификации вложенные циклы запрещены, но пользователь может ожидать, что новый <nn> 
            # автоматически закрывает предыдущий цикл. Сделаем закрытие без ошибки, но с предупреждением.
            if self.context['in_cycle']:
                self.errors.append(VMLError(line_num, "Вложенные циклы запрещены. Предыдущий цикл будет закрыт."))
                self._close_current_cycle(line_num, "встречен новый <nn>")
            if not self.context['author_found']:
                self.errors.append(VMLError(line_num, "Цикл <nn> вне блока автора"))
            self.context['in_cycle'] = True
            self.context['pair_stack'].append(('nn', line_num))
            self.context['cycle_tag_line'] = line_num

        elif main_tag == '/nn':
            # Закрытие цикла – закрываем текущее стихотворение и текущий цикл
            if self.context['in_poem']:
                self._close_current_poem(line_num, "закрытие цикла </nn>")
            if not self.context['pair_stack'] or self.context['pair_stack'][-1][0] != 'nn':
                self.errors.append(VMLError(line_num, "Непарный закрывающий тег </nn>"))
            else:
                self.context['pair_stack'].pop()
            if not self.context['in_cycle']:
                self.errors.append(VMLError(line_num, "Закрывающий тег </nn> вне открытого цикла"))
            self.context['in_cycle'] = False

        elif main_tag == '&':
            # Инципит (начало стихотворения) – закрываем предыдущее стихотворение
            if self.context['in_poem']:
                self._close_current_poem(line_num, "встречен новый <&>")
            if not self.context['author_found']:
                self.errors.append(VMLError(line_num, "Тег <&> вне блока автора"))
            self.context['in_poem'] = True
            self.context['poem_has_lines'] = False
            if not text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <&> без текста первой строки"))
            else:
                self.context['poem_has_lines'] = True   # инципит считается первой строкой

        elif main_tag == 'n':
            # Заголовок стихотворения – закрываем предыдущее стихотворение
            if self.context['in_poem']:
                self._close_current_poem(line_num, "встречен заголовок нового стихотворения <n>")
            if not self.context['author_found']:
                self.errors.append(VMLError(line_num, "Тег <n> вне блока автора"))
            self.context['title_mode'] = True
            self.context['in_poem'] = False
            self.context['poem_has_lines'] = False

        elif main_tag == '*':
            # Начало строфы
            if not self.context['in_poem']:
                self.errors.append(VMLError(line_num, "Тег <*> (строфа) вне стихотворения"))
            self.inside_stanza = True

        elif main_tag == 'rm':
            # Прозаическая вставка – допустима везде, не влияет на счёт строк
            pass

        elif main_tag == '#':
            # Дата написания
            if not self.context['in_poem']:
                self.errors.append(VMLError(line_num, "Тег даты <#> вне стихотворения"))
            if not text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <#> без значения"))

        elif main_tag == '%':
            # Место написания
            if not self.context['in_poem']:
                self.errors.append(VMLError(line_num, "Тег места <%> вне стихотворения"))
            if not text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <%> без значения"))

        # Дополнительная проверка для парных тегов иноязычных вставок <l-ISO>... </l-ISO>
        self._check_foreign_tags(line, line_num)

    def _check_foreign_tags(self, line, line_num):
        i = 0
        n = len(line)
        while i < n:
            if line[i] == '\\' and i+1 < n and line[i+1] == '<':
                i += 2
                continue
            if line[i] == '<':
                j = i+1
                while j < n and line[j] != '>':
                    j += 1
                if j < n:
                    tag_content = line[i+1:j]
                    if tag_content.startswith('l-') and tag_content not in ('l-',):
                        lang = tag_content[2:]
                        if not re.match(r'^[a-z]{3}$', lang):
                            self.errors.append(VMLError(line_num, f"Некорректный код языка в теге <{tag_content}> (ожидается три буквы)"))
                        self.context['pair_stack'].append((f'l-{lang}', line_num))
                    elif tag_content.startswith('/l-'):
                        lang = tag_content[3:]
                        if not self.context['pair_stack'] or not self.context['pair_stack'][-1][0].endswith(lang):
                            self.errors.append(VMLError(line_num, f"Непарный закрывающий тег </l-{lang}>"))
                        else:
                            self.context['pair_stack'].pop()
                    i = j+1
                else:
                    i += 1
            else:
                i += 1


# ------------------------------------------------------------
# Точка входа
# ------------------------------------------------------------
def main():
    if len(sys.argv) != 2:
        print("Использование: python vml_validator.py <файл.vml>")
        sys.exit(1)

    filepath = sys.argv[1]
    validator = VMLValidator()
    is_valid = validator.validate(filepath)
    for err in validator.errors:
        print(err)

    if is_valid:
        print("Документ VML валиден.")
        sys.exit(0)
    else:
        print("Документ VML содержит ошибки.")
        sys.exit(1)


if __name__ == "__main__":
    main()
