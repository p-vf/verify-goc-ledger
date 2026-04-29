import sys
import git
from git import Repo
from graphviz import Digraph

class GitVis:
    def __init__(self):
        self.dot = Digraph(comment="Git Repository Visualization", format="png")
        self.dot.attr(rankdir="TD")  # Top-to-bottom layout
        self.added_edges = set()
    
    def retrieve_commit_objects(self,repo):
        
        def get_dangling_leaves():
            fsck_output = repo.git.fsck('--no-reflogs', '--full', '--dangling', '--lost-found').splitlines()
            dangling_shas = set()
            for line in fsck_output:
                if "dangling commit" in line:
                    sha = line.split()[2]  # Extract the SHA from the fsck output
                    dangling_shas.add(sha)
            return dangling_shas
        
        def expand_dangling(sha):
            ret = set()
            commit = repo.commit(sha)
            for parent in commit.parents:
                ret.add(parent.hexsha)
                ret = ret.union(expand_dangling(parent.hexsha))
            return ret
                                
        normal_shas = set(commit.hexsha for commit in repo.iter_commits('--all'))
        dangling_leaves_shas = get_dangling_leaves()
        dangling_internals_shas = set()
        for sha in dangling_leaves_shas:
            dangling_internals_shas = dangling_internals_shas.union(expand_dangling(sha))
        
        # Combine reachable and dangling commit SHAs
        all_commit_shas = normal_shas.union(dangling_leaves_shas).union(dangling_internals_shas)
        
        # Retrieve full commit objects for each SHA
        all_commits = []
        for sha in all_commit_shas:
            try:
                commit = repo.commit(sha)
                all_commits.append(commit)
            except Exception as e:
                print(f"Error retrieving commit {sha}: {e}")
        return all_commits
    
    def commit2str(self,commit):
        return f'<<FONT COLOR="#ff0000">{commit.message.strip()}</FONT>:{commit.hexsha[:7]}>'

    def tree2str(self, tree):
        label = '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">
                    <TR><TD COLSPAN="3"><B>tree:{}</B></TD></TR>
            '''.format(tree.hexsha[:7])     
        # Check if the tree is empty
        if len(tree) == 0:
            # Add a row with placeholder values
            label += '''<TR>
                <TD>-</TD>
                <TD>-</TD>
                <TD>-</TD>
            </TR>'''
        else:
            # Add rows for each object in the tree
            for item in tree:
                obj_sha = item.hexsha
                obj_type = "blob" if item.type == "blob" else "tree"
                obj_name = item.name
                label += '''<TR>
                    <TD>{}</TD>
                    <TD>{}</TD>
                    <TD>{}</TD>
                </TR>'''.format(obj_type, obj_sha[:7], obj_name)
        label += "</TABLE>>"
        return label
    
    def blob2str(self,blob):
        return f'blob:{blob.hexsha[:7]}'
    
    def handle_commit(self,commit):
        self.dot.node(commit.hexsha, label=self.commit2str(commit), shape="box", style="filled", fillcolor="#99ffcc", fontsize="12")
        
        for parent in commit.parents:
            if (parent.hexsha, commit.hexsha) not in self.added_edges:
                self.dot.edge(commit.hexsha,parent.hexsha,arrowhead="normal",style="bold")
                self.added_edges.add((parent.hexsha, commit.hexsha))
        
        self.handle_tree(commit.tree,commit.hexsha)

    def handle_tree(self,tree, parent_hash):
        if (parent_hash, tree.hexsha) not in self.added_edges:
                lbl = self.tree2str(tree)
                self.dot.node(tree.hexsha, label=lbl, shape="plaintext", style="filled", fillcolor="#ffb3f1", fontsize="10",margin="0" )
                self.dot.edge(parent_hash, tree.hexsha,arrowhead="onormal",style="tapered")
                self.added_edges.add((parent_hash, tree.hexsha))
        
        for item in tree:
            match item.type:
                case "tree":
                    self.handle_tree(item,tree.hexsha)
                case "blob":
                    self.dot.node(item.hexsha, label=self.blob2str(item), shape="note", style="filled", fillcolor="#eeeeee", fontsize="10")
                    if (tree.hexsha, item.hexsha) not in self.added_edges:
                        self.dot.edge(tree.hexsha, item.hexsha,arrowhead="onormal",style="tapered")
                        self.added_edges.add((tree.hexsha, item.hexsha))
    
    def plot_HEAD(self,head_ref):
        if head_ref is None:return
        try:
            sha = head_ref.commit.hexsha
            self.dot.node("HEAD", label="HEAD", shape="cds", color="darkred", fontcolor="darkred",fontsize="11")
            if ("HEAD", sha) not in self.added_edges:
                self.dot.edge("HEAD", sha,color="darkred",arrowhead="vee")
                self.added_edges.add(("HEAD", sha))
        except Exception as e:return

    def plot_local_branches(self,branches):
        for branch in branches:
            if (branch.name, branch.commit.hexsha) not in self.added_edges:
                self.dot.node(branch.name, label=f"{branch.name}", shape="plaintext", fontcolor="darkred")
                self.dot.edge(branch.name, branch.commit.hexsha,color="darkred",arrowhead="vee")
                self.added_edges.add((branch.name, branch.commit.hexsha))

    def plot_remote_branches(self,remotes):
        for remote in remotes:
            for ref in remote.refs:
                if (ref.name, ref.commit.hexsha) not in self.added_edges:
                    self.dot.node(ref.name, label=f"{ref.name}", shape="plaintext", fontcolor="blue")
                    self.dot.edge(ref.name, ref.commit.hexsha,color="blue",arrowhead="onormal")
                    self.added_edges.add((ref.name, ref.commit.hexsha))

    def plot_tags(self,tags):
        for tag in tags:
            if (tag.name, tag.commit.hexsha) not in self.added_edges:
                self.dot.node(tag.name, label=f"Tag: {tag.name}", shape="plaintext", fontcolor="green")
                self.dot.edge(tag.name, tag.commit.hexsha)
                self.added_edges.add((tag.name, tag.commit.hexsha))

    def visualize(self,repo_path, output_file="repo_graph.png",plot_pointers=True):
        try: repo = Repo(repo_path)
        except git.InvalidGitRepositoryError:
            print(f"The path '{repo_path}' is not a valid Git repository.")
            return
        
        commits = self.retrieve_commit_objects(repo)
        for commit in commits:
            self.handle_commit(commit)

        if plot_pointers:
            self.plot_HEAD(repo.head.ref)
            self.plot_local_branches(repo.branches)
            self.plot_remote_branches(repo.remotes)
            self.plot_tags(repo.tags)

        self.dot.render(output_file, cleanup=True)
        print(f"Visualization saved to {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("syntax: repo_path [plot_pointers=true]")
        exit(0)
    repo_path = sys.argv[1]
    plot_pointers = True
    if len(sys.argv) > 2:
        plot_pointers = True if sys.argv[2].lower() in ["true","1","yes"] else False
    output_file = "repo_graph"
    
    gv = GitVis()
    gv.visualize(repo_path, output_file,plot_pointers)