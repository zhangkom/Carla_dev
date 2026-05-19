from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from fastapi import HTTPException, UploadFile

from .request_config import first_present, optional_string, read_conf_json


@dataclass(frozen=True)
class ZipBundle:
    midi_filename: str
    midi_bytes: bytes
    config: dict[str, Any]
    conf_filename: str
    raw_zip: bytes


def contains_cjk(value: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"
        for char in value
    )


def repair_zip_member_name(filename: str) -> str:
    if contains_cjk(filename):
        return filename

    for source_encoding in ("latin1", "cp437"):
        try:
            candidate = filename.encode(source_encoding).decode("gbk")
        except UnicodeError:
            continue
        if candidate != filename and contains_cjk(candidate):
            return candidate
    return filename


async def read_upload_bytes(upload: UploadFile) -> bytes:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"Uploaded file is empty: {upload.filename}")
    return data


async def clone_upload_for_background(upload: UploadFile | None) -> UploadFile | None:
    if upload is None:
        return None
    data = await read_upload_bytes(upload)
    return UploadFile(file=io.BytesIO(data), filename=upload.filename)


async def clone_render_uploads(
    midi: UploadFile | None,
    data: UploadFile | None,
    bundle: UploadFile | None,
) -> tuple[UploadFile | None, UploadFile | None, UploadFile | None]:
    if data is not None and bundle is not None:
        raise HTTPException(status_code=400, detail="Use either data or bundle for zip upload, not both")
    bundle_upload = data or bundle
    if midi is not None and bundle_upload is not None:
        raise HTTPException(status_code=400, detail="Use either midi upload or zip bundle upload, not both")
    if midi is None and bundle_upload is None:
        raise HTTPException(status_code=400, detail="Upload a zip bundle in data/bundle or a MIDI file in midi")

    cloned_midi = await clone_upload_for_background(midi)
    cloned_data = await clone_upload_for_background(data)
    cloned_bundle = await clone_upload_for_background(bundle)
    return cloned_midi, cloned_data, cloned_bundle


def zip_member_basename(value: object) -> str | None:
    path_text = optional_string(value, "conf.json route json path")
    if not path_text:
        return None
    return PurePosixPath(path_text.replace("\\", "/")).name.lower()


def find_zip_member_by_name(files: list[zipfile.ZipInfo], requested_name: str) -> zipfile.ZipInfo | None:
    normalized_request = requested_name.replace("\\", "/").lower().lstrip("/")
    requested_basename = PurePosixPath(normalized_request).name
    for info in files:
        normalized_member = info.filename.replace("\\", "/").lower().lstrip("/")
        if normalized_member == normalized_request:
            return info
    for info in files:
        member_basename = PurePosixPath(info.filename.replace("\\", "/")).name.lower()
        if member_basename == requested_basename:
            return info
    return None


def merge_route_json(config: dict[str, Any], route_config: dict[str, Any], *, label: str) -> None:
    for key in ("tracks", "vst", "sf2"):
        if key not in route_config:
            continue
        if key in config:
            raise HTTPException(status_code=400, detail=f"Duplicate {key} in conf.json and {label}")
        config[key] = route_config[key]


def load_linked_route_jsons(
    archive: zipfile.ZipFile,
    files: list[zipfile.ZipInfo],
    config: dict[str, Any],
) -> list[str]:
    loaded: list[str] = []
    refs = [
        ("vstConf", first_present(config.get("vstConf"), config.get("vst_conf"), config.get("vst_json"))),
        ("sf2Conf", first_present(config.get("sf2Conf"), config.get("sf2_conf"), config.get("sf2_json"))),
    ]
    for label, ref_value in refs:
        requested_name = zip_member_basename(ref_value)
        if not requested_name:
            continue
        member = find_zip_member_by_name(files, requested_name)
        if member is None:
            raise HTTPException(
                status_code=400,
                detail=f"conf.json {label} references {requested_name}, but it was not found in the zip bundle",
            )
        route_config = read_conf_json(archive.read(member), member.filename)
        merge_route_json(config, route_config, label=member.filename)
        loaded.append(repair_zip_member_name(member.filename))
    return loaded


async def load_zip_bundle(upload: UploadFile) -> ZipBundle:
    suffix = PurePosixPath(upload.filename or "bundle.zip").suffix.lower()
    if suffix != ".zip":
        raise HTTPException(status_code=400, detail="Zip bundle upload must be a .zip file")

    raw_zip = await read_upload_bytes(upload)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw_zip))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Uploaded zip bundle is invalid") from exc

    with archive:
        files = [info for info in archive.infolist() if not info.is_dir()]
        midi_members = [
            info
            for info in files
            if PurePosixPath(info.filename).suffix.lower() in {".mid", ".midi"}
        ]
        conf_members = [
            info
            for info in files
            if PurePosixPath(info.filename).name.lower() == "conf.json"
        ]
        if not conf_members:
            raise HTTPException(status_code=400, detail="Zip bundle must contain conf.json")
        if len(conf_members) > 1:
            raise HTTPException(status_code=400, detail="Zip bundle must contain only one conf.json")
        if not midi_members:
            raise HTTPException(status_code=400, detail="Zip bundle must contain a .mid or .midi file")
        if len(midi_members) > 1:
            raise HTTPException(status_code=400, detail="Zip bundle contains multiple MIDI files")

        conf_member = conf_members[0]
        midi_member = midi_members[0]
        config = read_conf_json(archive.read(conf_member), conf_member.filename)
        load_linked_route_jsons(archive, files, config)
        midi_bytes = archive.read(midi_member)
        if not midi_bytes:
            raise HTTPException(status_code=400, detail=f"MIDI file is empty: {midi_member.filename}")
        return ZipBundle(
            midi_filename=repair_zip_member_name(midi_member.filename),
            midi_bytes=midi_bytes,
            config=config,
            conf_filename=repair_zip_member_name(conf_member.filename),
            raw_zip=raw_zip,
        )
