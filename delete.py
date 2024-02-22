
import asyncio
from python_x509_pkcs11.pkcs11_handle import PKCS11Session



async def delete_keys():
    "We delete keys in a loop"

    # No need to delete keys in github actions.
    session = PKCS11Session()
    keys = await session.key_labels()
    for key_label, key_type in keys.items():
        if key_label == "test_pkcs11_device_do_not_use":
            continue
        print(f"Deleting {key_label}")
        await session.delete_keypair(key_label, key_type)

asyncio.run(delete_keys())
