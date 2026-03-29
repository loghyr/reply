/* Test basic RPC program syntax */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

program SIMPLE_PROG {
    version SIMPLE_V1 {
        void NULL(void) = 0;
        int ADD(int, int) = 1;
        string ECHO(string) = 2;
    } = 1;
} = 100000;
