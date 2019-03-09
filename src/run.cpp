#include <iostream>
#include <windows.h>
using namespace std;

int main()
{
	system("pip install bs4");
	system("pip install request");
	system("pip install lxml");
	system("python src/windows_main.py");
	return 0;
}
