#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VML Counter – подсчёт авторов, стихотворений, строк и циклов в VML-файле.
"""

import sys
import re


class VMLCounter:
    def __init__(self):
        self.author_count = 0
        self.poem_count = 0
        self.line_count = 0
        self.cycle_count = 0
        self.poems_in_cycles = 0
        self.cycle_stats = []

        # Состояния
        self.in_poem = False
        self.in_title = False
        self.incipit_seen = False
        self.cycle_stack = []          # стек кортежей (название_цикла, счётчик_стихов)

    def _open_cycle(self, cycle_name, line_num):
        """Открывает новый цикл."""
        self.cycle_stack.append([cycle_name.strip() or "(без названия)", 0])
        self.cycle_count += 1

    def _close_cycle(self, line_num):
        """Закрывает текущий цикл и сохраняет статистику."""
        if self.cycle_stack:
            name, cnt = self.cycle_stack.pop()
            self.cycle_stats.append((name, cnt))

    def _register_poem(self):
        """Увеличивает общий счётчик стихотворений и, если внутри цикла, увеличивает счётчик цикла."""
        self.poem_count += 1
        if self.cycle_stack:
            self.cycle_stack[-1][1] += 1
            self.poems_in_cycles += 1

    def _close_current_poem(self):
        """Закрывает текущее стихотворение (сброс флагов)."""
        if self.in_poem:
            self.in_poem = False
            self.in_title = False
            self.incipit_seen = False

    def _unescape(self, line):
        """Убирает экранирование: заменяет \<...> на <...>, но удаляет обратный слеш."""
        result = []
        i = 0
        n = len(line)
        while i < n:
            if line[i] == '\\' and i+1 < n and line[i+1] == '<':
                result.append('<')
                i += 2
                continue
            else:
                result.append(line[i])
                i += 1
        return ''.join(result)

    def _find_tags(self, line):
        """Возвращает список (тег, позиция) всех неэкранированных тегов в строке."""
        tags = []
        i = 0
        n = len(line)
        while i < n:
            if line[i] == '<':
                j = i + 1
                while j < n and line[j] != '>':
                    j += 1
                if j < n:
                    tag = line[i+1:j]
                    tags.append((tag, i))
                    i = j + 1
                else:
                    i += 1
            else:
                i += 1
        return tags

    def _strip_tags(self, line):
        """Удаляет все теги из строки (не трогая экранирование, оно уже обработано)."""
        return re.sub(r'<[^>]+>', '', line)

    def _extract_cycle_title(self, line, tag_start_pos):
        """Извлекает название цикла из строки после тега <nn>."""
        after_tag = line[tag_start_pos + len('<nn>'):].lstrip()
        return after_tag.strip()

    def count(self, filepath):
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()

        for line_num, raw_line in enumerate(lines, start=1):
            line = raw_line.rstrip('\n')
            if not line.strip():
                continue

            clean_line = self._unescape(line)
            tags = self._find_tags(clean_line)

            # Ищем основные теги в порядке появления
            main_tag = None
            main_tag_pos = None
            for tag, pos in tags:
                if tag in ('a', '&&', 'n', '&', 'rm', '#', '%', '*', 'nn', '/nn'):
                    main_tag = tag
                    main_tag_pos = pos
                    break

            if main_tag is None:
                # Строка без управляющих тегов — возможно, стихотворная строка
                if self.in_poem and not self.in_title:
                    text = self._strip_tags(clean_line)
                    if text.strip():
                        self.line_count += 1
                continue

            # Обработка тегов
            # ------------------------------------------------------------
            if main_tag == 'a':
                self._close_current_poem()
                while self.cycle_stack:
                    self._close_cycle(line_num)
                self.author_count += 1
                self.in_poem = False
                self.in_title = False
                self.incipit_seen = False

            elif main_tag == '&&':
                self._close_current_poem()
                self.in_poem = True
                self.in_title = False
                self.incipit_seen = False
                self._register_poem()

            elif main_tag == 'n':
                self._close_current_poem()
                self.in_poem = True
                self.in_title = True
                self.incipit_seen = False
                # Стихотворение ещё не засчитываем — нужен инципит

            elif main_tag == '&':
                # Если уже есть стихотворение с инципитом — закрываем его (начинаем новое)
                if self.in_poem and self.incipit_seen:
                    self._close_current_poem()
                    self.in_poem = True
                    self.in_title = False
                    self.incipit_seen = False
                # Если стихотворение не начато, начинаем
                if not self.in_poem:
                    self.in_poem = True
                    self.in_title = False
                    self.incipit_seen = False
                # Теперь in_poem == True, incipit_seen == False (новое или ранее начатое)
                # Регистрируем стихотворение при первом инципите
                if not self.incipit_seen:
                    self._register_poem()
                self.incipit_seen = True
                self.in_title = False

                # Первая стихотворная строка (инципит)
                text = self._strip_tags(clean_line)
                if text.strip():
                    self.line_count += 1

            elif main_tag == 'nn':
                self._close_current_poem()
                cycle_title = self._extract_cycle_title(clean_line, main_tag_pos)
                self._open_cycle(cycle_title, line_num)

            elif main_tag == '/nn':
                self._close_current_poem()
                self._close_cycle(line_num)

            elif main_tag in ('rm', '#', '%'):
                pass

            elif main_tag == '*':
                if self.in_poem and not self.in_title:
                    text = self._strip_tags(clean_line)
                    if text.strip():
                        self.line_count += 1

        # По окончании файла закрываем всё незакрытое
        self._close_current_poem()
        while self.cycle_stack:
            self._close_cycle(len(lines))

        return {
            'authors': self.author_count,
            'poems_total': self.poem_count,
            'poems_in_cycles': self.poems_in_cycles,
            'poems_outside_cycles': self.poem_count - self.poems_in_cycles,
            'cycles': self.cycle_count,
            'cycle_stats': self.cycle_stats,
            'lines': self.line_count,
        }


def main():
    if len(sys.argv) != 2:
        print("Использование: python vml_counter.py <файл.vml>")
        sys.exit(1)

    filepath = sys.argv[1]
    counter = VMLCounter()
    try:
        stats = counter.count(filepath)
        print(f"Авторов: {stats['authors']}")
        print(f"Всего стихотворений: {stats['poems_total']}")
        print(f"  из них в циклах: {stats['poems_in_cycles']}")
        print(f"  вне циклов: {stats['poems_outside_cycles']}")
        print(f"Циклов: {stats['cycles']}")
        if stats['cycle_stats']:
            print("\nСтатистика по циклам:")
            for title, cnt in stats['cycle_stats']:
                print(f"  «{title}»: {cnt} стихотворений")
        print(f"Стихотворных строк: {stats['lines']}")
    except Exception as e:
        print(f"Ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
