#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VML 1.0 Validator

Usage:
    python vml_validator.py <file.vml>
"""

import sys
import re

SINGLE_TAGS = {'a', '&', '&&', 'n', '#', '%', '*', 'rm'}
PAIR_TAGS_OPEN = {'nn', 'l-'}
PAIR_TAGS_CLOSE = {'/nn', '/l-'}
VALID_TAG_NAMES = {'a', 'n', '&', '&&', '#', '%', '*', 'rm', 'nn', '/nn'}

class VMLError:
    def __init__(self, line_num, message):
        self.line_num = line_num
        self.message = message
    def __str__(self):
        return f"Ошибка в строке {self.line_num}: {self.message}"

class VMLValidator:
    def __init__(self):
        self.errors = []
        self.lines = []
        self.context = {
            'author_found': False,
            'in_poem': False,
            'incipit_seen': False,
            'title_mode': False,
            'in_cycle': False,
            'cycle_tag_line': None,
            'pair_stack': [],
            'poem_has_lines': False,
            'current_author_name': None,
        }
        self.inside_stanza = False

    def _close_current_poem(self, line_num, reason="конец файла"):
        if self.context['in_poem']:
            if not self.context['incipit_seen']:
                self.errors.append(VMLError(line_num,
                    f"Стихотворение начато (через <&&> или <n>), но не содержит инципита (<&>) (закрыто: {reason})"))
            elif not self.context['poem_has_lines']:
                self.errors.append(VMLError(line_num,
                    f"Стихотворение не содержит ни одной стихотворной строки (закрыто: {reason})"))
            self.context['in_poem'] = False
            self.context['incipit_seen'] = False
            self.context['poem_has_lines'] = False
            self.context['title_mode'] = False
            self.inside_stanza = False

    def _close_current_cycle(self, line_num, reason="закрытие цикла"):
        if self.context['in_cycle']:
            if self.context['pair_stack'] and self.context['pair_stack'][-1][0] == 'nn':
                self.context['pair_stack'].pop()
            self.context['in_cycle'] = False

    def validate(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                content = f.read()
        except FileNotFoundError:
            self.errors.append(VMLError(0, f"Файл не найден: {filepath}"))
            return False
        except UnicodeDecodeError:
            self.errors.append(VMLError(0, "Файл не в кодировке UTF-8"))
            return False

        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            if '\r' in line:
                self.errors.append(VMLError(i, "Обнаружен CR (\\r) – используйте только LF"))
        if not lines:
            self.errors.append(VMLError(0, "Файл пуст"))
            return False

        self.lines = lines
        for idx, line in enumerate(lines, start=1):
            self._process_line(line, idx)

        if self.context['in_poem']:
            self._close_current_poem(len(self.lines), "конец файла")
        if not self.context['author_found']:
            self.errors.append(VMLError(0, "Документ не содержит тега автора <a>"))
        if self.context['pair_stack']:
            for tag, ln in self.context['pair_stack']:
                self.errors.append(VMLError(ln, f"Незакрытый тег <{tag}>"))
        return len(self.errors) == 0

    def _process_line(self, line, line_num):
        line = line.rstrip('\n')
        if self.context.get('title_mode', False):
            if '<&>' in line:
                self.context['title_mode'] = False
                self._process_line_content(line, line_num)
            return
        self._process_line_content(line, line_num)

    def _process_line_content(self, line, line_num):
        # ----- поиск тегов -----
        i, n = 0, len(line)
        tags = []
        while i < n:
            if line[i] == '\\' and i+1 < n and line[i+1] == '<':
                i += 2
                continue
            if line[i] == '<':
                j = i+1
                while j < n and line[j] != '>':
                    j += 1
                if j < n:
                    tags.append((i, line[i+1:j]))
                    i = j+1
                else:
                    self.errors.append(VMLError(line_num, f"Незакрытая угловая скобка: {line}"))
                    i += 1
            else:
                i += 1

        if not tags and line.strip() == '':
            return
        if not tags:
            if not self.context.get('in_poem', False):
                self.errors.append(VMLError(line_num, f"Строка вне стихотворения: {line[:50]}..."))
            else:
                if not self.context['incipit_seen']:
                    self.errors.append(VMLError(line_num, "Стихотворная строка до инципита (<&>) – используйте <&&> для эпиграфов"))
                self.context['poem_has_lines'] = True
            return

        # ----- определение основного тега -----
        main_tag = None
        for pos, tagname in tags:
            if tagname in SINGLE_TAGS or tagname in PAIR_TAGS_OPEN or tagname in PAIR_TAGS_CLOSE:
                main_tag = tagname
                break
            if tagname.startswith('l-') or tagname.startswith('m-'):
                continue

        if main_tag is None:
            if self.context.get('in_poem', False):
                self.context['poem_has_lines'] = True
            else:
                if tags:
                    self.errors.append(VMLError(line_num, f"Строка вне стихотворения с тегом: {tags[0][1]}"))
            return

        last_tag_end = tags[-1][0] + len(tags[-1][1]) + 2
        text_after_tags = line[last_tag_end:].lstrip()

        # ----- проверка формата тега -----
        tag_name = main_tag
        if tag_name.startswith('l-'):
            if not re.match(r'l-[1-9][0-9]*$', tag_name):
                self.errors.append(VMLError(line_num, f"Неверный тег лесенки: <{tag_name}>"))
        elif tag_name.startswith('/l-'):
            if not re.match(r'/l-[1-9][0-9]*$', tag_name):
                self.errors.append(VMLError(line_num, f"Неверный закрывающий тег: <{tag_name}>"))
        elif tag_name.startswith('m-'):
            if not re.match(r'm-[SRA][A-Za-zА-Яа-я0-9*]*', tag_name):
                self.errors.append(VMLError(line_num, f"Неверный метрический тег: <{tag_name}>"))
        elif tag_name not in VALID_TAG_NAMES and not (tag_name.startswith('l-') or tag_name.startswith('/l-')):
            self.errors.append(VMLError(line_num, f"Неизвестный тег: <{tag_name}>"))

        # ----- семантическая обработка -----
        if main_tag == 'a':
            self.context['title_mode'] = False
            if self.context['in_poem']:
                self._close_current_poem(line_num, "встречен <a>")
            if self.context['in_cycle']:
                self._close_current_cycle(line_num, "встречен <a>")
            self.context['author_found'] = True
            self.context['in_poem'] = False
            self.context['incipit_seen'] = False
            self.context['in_cycle'] = False
            self.context['poem_has_lines'] = False
            self.context['current_author_name'] = text_after_tags.strip()
            if not text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <a> без имени автора"))
            if self.context['pair_stack']:
                for tag, ln in self.context['pair_stack']:
                    self.errors.append(VMLError(ln, f"Незакрытый тег <{tag}> перед новым автором"))
                self.context['pair_stack'].clear()

        elif main_tag == '&&':
            if self.context['in_poem']:
                self._close_current_poem(line_num, "встречен <&&>")
            if not self.context['author_found']:
                self.errors.append(VMLError(line_num, "Тег <&&> вне блока автора"))
            if text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <&&> не должен содержать текста"))
            self.context['in_poem'] = True
            self.context['incipit_seen'] = False
            self.context['poem_has_lines'] = False
            self.context['title_mode'] = False

        elif main_tag == 'n':
            if self.context['in_poem']:
                self._close_current_poem(line_num, "встречен заголовок <n> нового стихотворения")
            if not self.context['author_found']:
                self.errors.append(VMLError(line_num, "Тег <n> вне блока автора"))
            self.context['in_poem'] = True
            self.context['incipit_seen'] = False
            self.context['poem_has_lines'] = False
            self.context['title_mode'] = True

        elif main_tag == '&':
            if not self.context['author_found']:
                self.errors.append(VMLError(line_num, "Тег <&> вне блока автора"))
                return

            # Если уже есть открытое стихотворение с инципитом – закрываем его и начинаем новое
            if self.context['in_poem'] and self.context['incipit_seen']:
                self._close_current_poem(line_num, "встречен следующий <&>")

            # Если стихотворение не открыто (или только что закрыли) – открываем
            if not self.context['in_poem']:
                self.context['in_poem'] = True
                self.context['incipit_seen'] = False
                self.context['poem_has_lines'] = False
                self.context['title_mode'] = False

            # Теперь in_poem == True и incipit_seen == False
            self.context['title_mode'] = False
            self.context['incipit_seen'] = True
            if not text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <&> без текста первой строки"))
            else:
                self.context['poem_has_lines'] = True

        elif main_tag == '*':
            if not self.context['in_poem']:
                self.errors.append(VMLError(line_num, "Тег <*> (строфа) вне стихотворения"))
            self.inside_stanza = True

        elif main_tag == 'rm':
            if not self.context['in_poem']:
                self.errors.append(VMLError(line_num, "Прозаическая вставка <rm> вне стихотворения"))

        elif main_tag == '#':
            if not self.context['in_poem']:
                self.errors.append(VMLError(line_num, "Тег даты <#> вне стихотворения"))
            if not text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <#> без значения"))

        elif main_tag == '%':
            if not self.context['in_poem']:
                self.errors.append(VMLError(line_num, "Тег места <%> вне стихотворения"))
            if not text_after_tags.strip():
                self.errors.append(VMLError(line_num, "Тег <%> без значения"))

        elif main_tag == 'nn':
            if self.context['in_poem']:
                self._close_current_poem(line_num, "встречен <nn> (начало цикла)")
            if self.context['in_cycle']:
                self.errors.append(VMLError(line_num, "Вложенные циклы запрещены. Предыдущий цикл будет закрыт."))
                self._close_current_cycle(line_num, "встречен новый <nn>")
            if not self.context['author_found']:
                self.errors.append(VMLError(line_num, "Цикл <nn> вне блока автора"))
            self.context['in_cycle'] = True
            self.context['pair_stack'].append(('nn', line_num))
            self.context['cycle_tag_line'] = line_num

        elif main_tag == '/nn':
            if self.context['in_poem']:
                self._close_current_poem(line_num, "закрытие цикла </nn>")
            if not self.context['pair_stack'] or self.context['pair_stack'][-1][0] != 'nn':
                self.errors.append(VMLError(line_num, "Непарный закрывающий тег </nn>"))
            else:
                self.context['pair_stack'].pop()
            if not self.context['in_cycle']:
                self.errors.append(VMLError(line_num, "Закрывающий тег </nn> вне открытого цикла"))
            self.context['in_cycle'] = False

        self._check_foreign_tags(line, line_num)

    def _check_foreign_tags(self, line, line_num):
        i, n = 0, len(line)
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
                            self.errors.append(VMLError(line_num, f"Некорректный код языка: <{tag_content}>"))
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
