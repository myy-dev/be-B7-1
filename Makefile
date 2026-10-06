.PHONY: todos

# 남은 TODO·FIXME·XXX·HACK을 파일 경로순으로 모아 본다.
# rg(ripgrep)가 있으면 쓰고, 없으면 git grep으로 대체한다.
# 이 Makefile 자신은 검색에서 뺀다(패턴·설명에 같은 낱말이 들어 있어 자기 자신이 잡힘).
todos:
	@if command -v rg >/dev/null 2>&1; then \
		rg -n --sort path -g '!Makefile' -e 'TODO|FIXME|XXX|HACK' || true; \
	else \
		git grep -n -E 'TODO|FIXME|XXX|HACK' -- ':!Makefile' || true; \
	fi
