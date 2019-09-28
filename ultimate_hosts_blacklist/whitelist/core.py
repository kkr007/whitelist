"""
The whitelisting tool from the Ultimate-Hosts-Blacklist project.

Provide the main logic.

License:
::


    MIT License

    Copyright (c) 2018, 2019 Ultimate-Hosts-Blacklist
    Copyright (c) 2018, 2019 Nissar Chababy
    Copyright (c) 2019 Mitchell Krog

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""
# pylint: disable=bad-continuation, logging-format-interpolation
import logging
from itertools import filterfalse
from multiprocessing import Pool
from os import cpu_count

from domain2idna import get as domain2idna
from PyFunceble import load_config
from PyFunceble.check import Check

from ultimate_hosts_blacklist.helpers import Download, File, Regex
from ultimate_hosts_blacklist.whitelist.configuration import Configuration
from ultimate_hosts_blacklist.whitelist.parser import Parser


def _is_whitelisted(line, manifest):  # pylint: disable=too-many-branches
    """
        Check if the given line is whitelisted.
        """

    line = line.strip()

    if not line:
        logging.debug("Empty line whitelisted by default.")
        return True, line

    logging.debug("Given line: {0}".format(repr(line)))

    if isinstance(line, str):
        to_check = line.split()[-1]

        url_base = Check(to_check).is_url(return_base=True)

        if url_base is not False:  # pragma: no cover
            to_check = url_base
    else:  # pragma: no cover
        raise ValueError("expected {0}. {2} given.".format(type(str), type(line)))

    logging.debug("To check: {0}".format(repr(to_check)))

    if manifest:
        if to_check.startswith("www."):
            bare = to_check[4:]
        else:
            bare = to_check

        if bare[:4] in manifest["strict"] and to_check in manifest["strict"][bare[:4]]:
            logging.debug(
                "Line {0} whitelisted by {1} rule: {2}.".format(
                    repr(line), repr("strict"), repr(line)
                )
            )
            return True, line

        if (
            bare[:4] in manifest["present"]
            and to_check in manifest["present"][bare[:4]]
        ):
            logging.debug(
                "Line {0} whitelisted by {1} rule.".format(repr(line), repr("present"))
            )
            return True, line

        if bare[-3:] in manifest["ends"]:  # pragma: no cover
            for rule in manifest["ends"][bare[-3:]]:
                if to_check.endswith(rule):
                    logging.debug(
                        "Line {0} whitelisted by {1} rule: {2}.".format(
                            repr(line), repr("ends"), repr(rule)
                        )
                    )
                    return True, line

        if (
            manifest["regex"]
            and Regex(to_check, manifest["regex"], return_data=False).match()
        ):
            logging.debug(
                "Line {0} whitelisted by {1} rule.".format(repr(line), repr("regex"))
            )
            return True, line

    logging.debug("Line {0} not whitelisted, no rule matched.".format(repr(line)))
    return False, line


class Core:  # pylint: disable=too-few-public-methods,too-many-arguments, too-many-instance-attributes
    """
    Brain of our system.
    """

    def __init__(
        self,
        output_file=None,
        secondary_whitelist=None,
        secondary_whitelist_file=None,
        anti_whitelist=None,
        anti_whitelist_file=None,
        use_official=True,
        multiprocessing=True,
        processes=0,
        logging_level=logging.INFO,
        logging_into_file=False,
    ):

        if logging_into_file:
            logging_file = "uhb_whitelist_debug"
        else:
            logging_file = None

        logging.basicConfig(
            format="%(asctime)s - %(levelname)s -- %(message)s",
            level=logging_level,
            filename=logging_file,
        )

        self.secondary_whitelist_file = secondary_whitelist_file
        self.secondary_whitelist_list = secondary_whitelist
        self.anti_whitelist_list = anti_whitelist
        self.anti_whitelist_file = anti_whitelist_file

        self.output = output_file
        self.use_core = use_official

        parser = Parser()
        self.whitelist_process = parser.parse(self.__get_whitelist_list_to_parse())

        self.multiprocessing = multiprocessing

        if self.multiprocessing:
            if not processes:
                self.processes = cpu_count() // 2
            else:
                self.processes = processes

        load_config(generate_directory_structure=False)

    @classmethod
    def __get_our_special_rules(cls):
        """
        Return some special rules which should be always added to the system.
        """

        return [
            # Match 0.0.0.0–0.255.255.255
            r"REG ^(0\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 10.0.0.0–10.255.255.255
            r"REG ^(10\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 100.64.0.0–100.127.255.255
            r"REG ^(100\.(0?6[4-9]|0?[7-9][0-9]|1[0-1][0-9]|12[0-7])\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 127.0.0.0–127.255.255.255
            r"REG ^(127\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 169.254.0.0–169.254.255.255
            r"REG ^(169\.254\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 172.16.0.0–172.31.255.255
            r"REG ^(172\.(0?1[6-9]|0?2[0-9]|0?3[0-1])\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 192.0.0.0–192.0.0.255
            r"REG ^(192\.0\.0\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 192.0.2.0–192.0.2.255
            r"REG ^(192\.0\.2\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 192.88.99.0–192.88.99.255
            r"REG ^(192\.88\.99\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 192.168.0.0–192.168.255.255
            r"REG ^(192\.168\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 198.18.0.0–198.19.255.255
            r"REG ^(198\.(0?1[8-9])\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 198.51.100.0–198.51.100.255
            r"REG ^(198\.51\.100\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 203.0.113.0–203.0.113.255
            r"REG ^(203\.0\.113\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,}))$",  # pylint: disable=line-too-long
            # Match 224.0.0.0–239.255.255.255
            r"REG ^(22[4-9]|23[0-9])\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,})$",  # pylint: disable=line-too-long
            # Match 240.0.0.0–255.255.255.254
            r"REG ^(24[0-9]|25[0-5])\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[0-9]{1,}\/[0-9]{1,})$",  # pylint: disable=line-too-long
            # Match 255.255.255.255
            r"255.255.255.255",  # pylint: disable=line-too-long
        ]

    def __get_whitelist_list_to_parse(self):
        """
        Return the not parsed/formatted whitelist list.
        """

        if self.use_core:
            result = (
                Download(Configuration.links["core"], destination=None)
                .link()
                .split("\n")
            )
        else:
            result = []

        result.extend(self.__get_our_special_rules())

        if self.secondary_whitelist_file and isinstance(
            self.secondary_whitelist_file, list
        ):  # pragma: no cover
            for file in self.secondary_whitelist_file:
                result.extend(file.read().splitlines())

        if self.secondary_whitelist_list and isinstance(
            self.secondary_whitelist_list, list
        ):
            result.extend(self.secondary_whitelist_list)

        if self.anti_whitelist_file and isinstance(
            self.anti_whitelist_file, list
        ):  # pragma: no cover

            anti_content = []

            for anti_file in self.anti_whitelist_file:
                anti_content.extend(anti_file.read().splitlines())

            result = list(set(result) - set(anti_content))

        if self.anti_whitelist_list and isinstance(self.anti_whitelist_list, list):
            result = list(set(result) - set(self.anti_whitelist_list))

        return result

    @classmethod
    def format_upstream_line(cls, line):  # pylint: disable=too-many-branches
        """
        Format the given line in order to habe the domain in IDNA format.

        :param line: The line to format.
        :type line: str
        """

        if line.startswith("#"):
            return line

        regex_delete = r"localhost$|localdomain$|local$|broadcasthost$|0\.0\.0\.0$|allhosts$|allnodes$|allrouters$|localnet$|loopback$|mcastprefix$"  # pylint: disable=line-too-long
        comment = ""
        element = ""
        tabs = "\t"
        space = " "

        if Regex(line, regex_delete, return_data=True).match():  # pragma: no cover
            return line

        tabs_position, space_position = (line.find(tabs), line.find(space))

        if not tabs_position == -1:
            separator = tabs
        elif not space_position == -1:
            separator = space
        else:
            separator = None

        if separator:
            splited_line = line.split(separator)

            index = 0
            while index < len(splited_line):
                if (
                    splited_line[index]
                    and not Regex(
                        splited_line[index], regex_delete, return_data=False
                    ).match()
                ):
                    break
                index += 1

            if "#" in splited_line[index]:
                index_comment = splited_line[index].find("#")

                if index_comment > -1:
                    comment = splited_line[index][index_comment:]

                    element = splited_line[index].split(comment)[0]
                    splited_line[index] = domain2idna(element) + comment
            else:
                splited_line[index] = domain2idna(splited_line[index])

            return separator.join(splited_line)
        return domain2idna(line)

    def __write_output(self, line):  # pragma: no cover
        """
        Write the output file.

        :param line: One or multiple lines.
        :type line: str or list

        :return: The lines
        """

        line = [x.strip() for x in line if x.strip()]

        if self.output:
            if isinstance(line, list):
                line = "\n".join(line)

            File(self.output).write("{0}\n".format(line), overwrite=True)

        return line

    def _get_content(
        self, input_file=None, string=None, items=None, already_formatted=False
    ):  # pragma: no cover
        """
        Return the content we have to check.
        """

        result = []

        if input_file:
            result.extend(input_file.read().splitlines())
        if string:
            if not already_formatted:
                for line in string.split("\n"):
                    result.append(self.format_upstream_line(line))
            else:
                result.extend(string.split("\n"))

        if items:
            if not already_formatted:
                for line in items:
                    result.append(self.format_upstream_line(line))
            else:
                result.extend(items)

        del input_file, items, string

        return result

    def filter(self, file=None, string=None, items=None, already_formatted=False):
        """
        Process the whitelisting.
        """

        if self.whitelist_process:

            if self.multiprocessing:
                result = []

                with Pool(processes=self.processes) as pool:
                    for whitelisted, line in pool.starmap(
                        _is_whitelisted,
                        [
                            [x, self.whitelist_process]
                            for x in self._get_content(
                                input_file=file,
                                string=string,
                                items=items,
                                already_formatted=already_formatted,
                            )
                        ],
                    ):
                        if whitelisted is False:
                            result.append(line)

                return self.__write_output(result)

            return self.__write_output(
                list(
                    filterfalse(
                        lambda x: _is_whitelisted(x, self.whitelist_process)[0] is True,
                        self._get_content(
                            input_file=file,
                            string=string,
                            items=items,
                            already_formatted=already_formatted,
                        ),
                    )
                )
            )

        return self.__write_output(
            self._get_content(
                input_file=file,
                string=string,
                items=items,
                already_formatted=already_formatted,
            )
        )  # pragma: no cover