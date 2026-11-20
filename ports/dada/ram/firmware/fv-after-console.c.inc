/* In the dedicated dada RAM probe only. BDS already has its text console.
 * No Boot#### option, disk fallback, filesystem or writable ESP is needed. */
static EFI_GUID mDadaRamApp = { 0x772ee312, 0xe97a, 0x45fe,
                                { 0x96, 0xfa, 0x24, 0xec, 0x25, 0xaa, 0xb3, 0x8e } };

EFI_DEVICE_PATH_PROTOCOL**
EFIAPI
DeviceBootManagerAfterConsole ()
{
  EFI_DEVICE_PATH_PROTOCOL *Path = NULL;
  EFI_HANDLE Child = NULL;
  EFI_STATUS Status;

  Print (L"DADA_UEFI: starting Linux from firmware volume\r\n");
  Status = GetFileDevicePathFromAnyFv (&mDadaRamApp, EFI_SECTION_PE32, 0, &Path);
  if (!EFI_ERROR (Status)) {
    Status = gBS->LoadImage (FALSE, gImageHandle, Path, NULL, 0, &Child);
    FreePool (Path);
  }
  if (!EFI_ERROR (Status)) {
    Status = gBS->StartImage (Child, NULL, NULL);
  }
  Print (L"DADA_UEFI: Linux returned (%r); cold reset in 15 seconds\r\n", Status);
  gBS->Stall (15000000);
  gRT->ResetSystem (EfiResetCold, EFI_SUCCESS, 0, NULL);
  CpuDeadLoop ();
  return NULL;
}
