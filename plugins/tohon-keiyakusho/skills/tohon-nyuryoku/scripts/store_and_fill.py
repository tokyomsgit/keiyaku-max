"""Supabase保存成功後に、変更していないfill_tohon.pyを実行する。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from supabase_store import save_to_supabase, StoreError


def run(json_path, template_path, output, *, house_number, source_path, db_context=None, mapping=None):
    source, template, output = Path(json_path), Path(template_path), Path(output)
    if output.exists() or output.resolve() == template.resolve():
        raise StoreError('出力先にファイルがあります。別の出力先を指定してください。')
    if not template.is_file(): raise StoreError('契約書ひな形が見つかりません。')
    data = json.loads(source.read_text(encoding='utf8'))
    # Validate the template without changing it or creating an Excel output.
    import openpyxl
    spec = json.loads(Path(mapping or Path(__file__).with_name('mapping.json')).read_text(encoding='utf8'))
    wb = openpyxl.load_workbook(template,read_only=True)
    valid = spec['sheet'] in wb.sheetnames and any(n in wb.defined_names for n in (spec['single']['所有者.氏名'],spec['floors']['total']))
    wb.close()
    if not valid: raise StoreError('名前定義付きの契約書ひな形を指定してください。')
    before = source.read_bytes()
    result = save_to_supabase(data,house_number=house_number,source_path=source_path,**(db_context or {}))
    if source.read_bytes() != before: raise StoreError('中間JSONが変更されたため作成を停止しました。')
    command = [sys.executable,'-X','utf8',str(Path(__file__).with_name('fill_tohon.py')),str(source),str(template),'-o',str(output)]
    if mapping: command += ['-m',str(mapping)]
    completed = subprocess.run(command,check=False)
    return result, completed.returncode


def main():
    parser = argparse.ArgumentParser(description='DB保存後に契約書を作成します。')
    parser.add_argument('json_path'); parser.add_argument('template_path')
    parser.add_argument('-o','--output',required=True)
    parser.add_argument('--house-number',required=True,help='原文確認済みの完全な家屋番号')
    parser.add_argument('--source',required=True,help='元の謄本PDF')
    parser.add_argument('--db-context',help='DB専用の補足情報JSON。既存中間JSONとは別に指定')
    parser.add_argument('-m','--mapping')
    args = parser.parse_args()
    try:
        context = json.loads(Path(args.db_context).read_text(encoding='utf8')) if args.db_context else None
        result,code = run(args.json_path,args.template_path,args.output,house_number=args.house_number,
            source_path=args.source,db_context=context,mapping=args.mapping)
        print('Supabase保存完了。要確認の差分：'+str(result['diffs_created'])+'件')
        for warning in result.get('warnings',[]): print('要確認：'+warning)
        return code
    except (StoreError,OSError,ValueError):
        print('保存または入力内容の確認に失敗しました。契約書の作成を停止しました。管理者へ連絡してください。')
        return 2


if __name__ == '__main__':
    sys.exit(main())
