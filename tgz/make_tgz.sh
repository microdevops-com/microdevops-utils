#!/bin/bash
if [ `dirname $0` != "." ]; then
        echo "You should run this script from `dirname $0`"
        exit;
fi
rm -rf sysadmws-utils
cp -R ../deb/sysadmws-utils .
rm -rf sysadmws-utils/DEBIAN
sudo chown -R root:root sysadmws-utils
sudo tar zcvf sysadmws-utils.tar.gz -C sysadmws-utils .
sudo chown -R `whoami`:`whoami` sysadmws-utils
rm -rf sysadmws-utils
