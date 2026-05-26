// SPDX-License-Identifier: GPL-2.0-only
/*
 * ec_io.c - ACPI EC raw I/O via misc device
 *
 * Based on ec_sys.c by Thomas Renninger <trenn@suse.de>
 * Modified to use a misc device instead of debugfs so that raw EC
 * read/write access works under Secure Boot kernel lockdown
 * (LOCKDOWN_DEBUGFS blocks all writable debugfs files at open time).
 *
 * Creates /dev/ec_io (mode 0600, root only) supporting seekable
 * byte-level read/write over the 256-byte EC address space.
 */

#include <linux/kernel.h>
#include <linux/acpi.h>
#include <linux/module.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>

MODULE_AUTHOR("Thomas Renninger <trenn@suse.de>");
MODULE_DESCRIPTION("ACPI EC raw I/O misc device (Secure Boot lockdown compatible)");
MODULE_LICENSE("GPL");

#define EC_SPACE_SIZE 256

static loff_t ec_io_llseek(struct file *f, loff_t offset, int whence)
{
	return fixed_size_llseek(f, offset, whence, EC_SPACE_SIZE);
}

static ssize_t ec_io_read(struct file *f, char __user *buf,
			   size_t count, loff_t *off)
{
	unsigned int size = EC_SPACE_SIZE;
	loff_t init_off = *off;
	int err = 0;

	if (*off >= size)
		return 0;
	if (*off + count >= size) {
		size -= *off;
		count = size;
	} else {
		size = count;
	}

	while (size) {
		u8 byte_read;
		err = ec_read(*off, &byte_read);
		if (err)
			return err;
		if (put_user(byte_read, buf + *off - init_off)) {
			if (*off - init_off)
				return *off - init_off; /* partial read */
			return -EFAULT;
		}
		*off += 1;
		size--;
	}
	return count;
}

static ssize_t ec_io_write(struct file *f, const char __user *buf,
			    size_t count, loff_t *off)
{
	unsigned int size = count;
	loff_t init_off = *off;
	int err = 0;

	if (*off >= EC_SPACE_SIZE)
		return 0;
	if (*off + count >= EC_SPACE_SIZE) {
		size = EC_SPACE_SIZE - *off;
		count = size;
	}

	while (size) {
		u8 byte_write;
		if (get_user(byte_write, buf + *off - init_off)) {
			if (*off - init_off)
				return *off - init_off; /* partial write */
			return -EFAULT;
		}
		err = ec_write(*off, byte_write);
		if (err)
			return err;
		*off += 1;
		size--;
	}
	return count;
}

static const struct file_operations ec_io_fops = {
	.owner	= THIS_MODULE,
	.llseek	= ec_io_llseek,
	.read	= ec_io_read,
	.write	= ec_io_write,
};

static struct miscdevice ec_io_dev = {
	.minor	= MISC_DYNAMIC_MINOR,
	.name	= "ec_io",
	.fops	= &ec_io_fops,
	.mode	= 0600,
};

static int __init ec_io_init(void)
{
	return misc_register(&ec_io_dev);
}

static void __exit ec_io_exit(void)
{
	misc_deregister(&ec_io_dev);
}

module_init(ec_io_init);
module_exit(ec_io_exit);
